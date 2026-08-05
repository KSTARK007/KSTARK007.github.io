---
title: "Agentic Coding in the Wild: Characterizing GitHub Copilot at Production Scale"
author: "Kiran Hombal"
canonical_url: "https://kstark007.github.io/blog/agentic-coding-in-the-wild/"
date_published: "2026-08-05T09:00:00-05:00"
description: "A visual reading of the first production-scale characterization of an AI coding agent: sampled GitHub Copilot traces covering 13.5M sessions, 3.2M users and 760.5M LLM calls."
based_on_paper: "Agentic Coding in the Wild: Characterizing GitHub Copilot at Production Scale"
paper_authors: "Banruo Liu, Haoran Qiu, Íñigo Goiri, Rodrigo Fonseca, Ricardo Bianchini, Esha Choukse"
paper_arxiv: "https://arxiv.org/abs/2608.00101"
paper_arxiv_id: "2608.00101"
keywords: ["AI coding agents", "GitHub Copilot", "LLM serving", "KV cache", "workload characterization", "prefix caching", "context compaction"]
---

# Agentic Coding in the Wild

*Characterizing GitHub Copilot at Production Scale*

A reading by [Kiran Hombal](https://kstark007.github.io/) of the paper **Agentic Coding in the Wild: Characterizing GitHub Copilot at Production Scale** by Banruo Liu, Haoran Qiu, Íñigo Goiri, Rodrigo Fonseca, Ricardo Bianchini, Esha Choukse (Microsoft Azure Research and UIUC), published as [arXiv:2608.00101](https://arxiv.org/abs/2608.00101). The findings are the authors'; the reading, the charts and any errors in them are not.

Canonical HTML version: https://kstark007.github.io/blog/agentic-coding-in-the-wild/

---

## What is this

A reading of the _Agentic Coding in the Wild_ paper, the first production-scale measurement of an AI coding agent, by researchers at Microsoft Azure Research and UIUC. The findings are theirs. I have just tried to bring out the parts I found most interesting and lay them out in a way that is easy to digest.

Anonymized telemetry from GitHub Copilot’s coding agent in Visual Studio and VS Code, covering one week. Structural metadata only: timings, token counts excluding reasoning tokens, model and tool names, success and failure. No prompts, no code, no user identity. The authors analyse a **sampled** subset of the traces except where they compute aggregate metrics, and the sample is drawn from US regions spanning at most three timezones.

- **Sessions**: 13.5M
- **User turns**: 95.1M
- **Users**: 3.2M
- **LLM calls**: 760.5M
- **Tool calls**: 774.7M
- **Prompt tokens**: 44.9T
- **Completion tokens**: 39.3B
- **Models / tools**: 27+ / 45+

Table 3 · Sampled traces, first week of june 2026

## A coding agent is not a chatbot with tools

Serving systems like vLLM and SGLang were built for a workload of independent, short-lived, stateless requests. Scheduling, admission control and cache management all happen at the granularity of a single request.

Agentic coding violates that model on almost every axis. One user message expands into a turn of 4.5 model calls at the median; the median session runs 15 across three turns. Later actions often depend on the exact output of previous tool executions, execution alternates between GPU and CPU work, and within a turn the prompt prefix grows monotonically as history accumulates.

Chat and completionCoding agent

- **Calls per interaction**: 115 median, 40+ mean
- **Token asymmetry**: ModerateExtreme: 68K prompt, 247 output
- **State between calls**: Stateless, replayedTight sequential dependency
- **Resource pattern**: GPU onlyGPU and CPU/IO alternation
- **Session duration**: SecondsSeconds to minutes or hours
- **Failure handling**: Manual retryRetry loops, 48x P95 blowup
- **Cache sensitivity**: Low, requests independentHigh, prefix-sharing in the loop
- **Autonomy level**: User-drivenAgent-driven, 87% of LLM calls

Table 2

## The loop runs itself

Every turn begins with exactly one user-initiated call. Everything after it is the agent deciding, on its own, to keep going.

### A single turn: reason, act, observe, and recover

Figure 8

LLM call9.1s

get_file76ms

LLM call4s

run_build28ms

LLM call3.8s

get_errors30ms

LLM call6.9s

run_commandfailed

the retry burst starts here

LLM call4.3s

get_errors44ms

LLM call5.9s

edit_file1s

LLM call7.4s

run_build52ms

LLM call12.1s

run_command17ms

- continues to 36 LLM calls and 35 tool calls in total

LLM callTool callFailure, and the recovery after it

Durations are the ones Figure 8 prints; the failed call’s duration is not given.

Inference dominates the clock; tool results are disproportionately expensive in context, 28% of prompt tokens for 4.7% of the time. The failed `run_command` does not end the turn: in an agentic loop a failure triggers an autonomous recovery attempt, cascading into more inference with a growing context window.

A deep-loop turn alternates LLM calls of several seconds with tool calls of tens of milliseconds. A failed run_command triggers an autonomous retry burst that runs the turn to 36 LLM calls.

Across the whole population the ratio of LLM calls to tool invocations sits at almost exactly **1:1**, and it holds across the whole distribution rather than only on average, with one exception the authors name: the 20.2% of turns that call no tools at all. Most model calls end in an action; most actions immediately provoke another model call. Reasoning without action and action without reasoning are both rare.

Takeaway 1

The agentic loop enforces a strict 1:1 coupling. Serving systems must treat an LLM call and its tool invocation as an inter-dependent pair, not two independent requests.

After a user message the agent runs a mean of 6.6 LLM calls before handing control back. That makes 87% of all LLM calls agent-initiated rather than user-initiated, so most serving load originates from autonomous execution rather than from a person pressing enter, and the distribution is skewed: a small fraction of requests trigger long chains that account for a disproportionate share of the load.

Takeaway 2

87% of LLM calls are agent-initiated. User request arrivals alone do not predict LLM load, so capacity planning needs session- or turn-level modeling of the autonomous chains.

Execution is also stubbornly serial. 63.3% of all turns show some overlap, but the median concurrency is only 1.15 and P90 reaches 1.4. Concurrency appears in the middle of a turn, during exploration, then collapses back to one as the agent converges on a decision that depends on every preceding branch.

### LLM calls and tool calls per turn track each other

Figure 6; Table 5

LLM calls / turn, Tool calls / turn by Calls per turnLLM calls / turn: 4.5 median at the 50th percentile. Tool calls / turn: 4 median at the 50th percentile0.00.20.40.60.81.0CDF of turns110100Calls per turn4.5 median4 median

- LLM calls / turn
- Tool calls / turn

The two curves are almost the same curve. The gap at the left edge is the 20.2% of turns that are pure reasoning and call no tools at all.

The distributions of LLM calls and tool calls per turn are nearly identical across the whole range, confirming one-to-one coupling.

### How much of a turn actually runs in parallel

Figure 7

Distribution of LLM parallelism degreeParallelism: 1.15 median at the 50th percentile0.00.20.40.60.81.0CDF of turns1.01.21.41.61.8LLM parallelism degree1.15 median

Measured only over turns that overlap at all. Even there, two calls in flight at once is close to the ceiling.

Among turns showing any overlap, the median parallelism degree is only 1.15 and P90 is 1.4.

Takeaway 3

Agentic execution is predominantly serial. Concurrency stays shallow and sits in the middle of a turn, creating occasional straggler dependencies and KV-cache contention between two or three calls of the same session.

## The median session is nothing like the mean one

Half of all sessions finish in 4.2 minutes with three turns and fifteen model calls. The average session runs 62.6 minutes. That is a mean-to-median ratio of 14.9x: a small fraction of long-running sessions accounts for a disproportionate share of all coding-agent activity, and at P90 a session is still going after nearly three hours.

The paper’s conclusion from this spread is that serving systems have to reason about workflow progress rather than treat every turn as a homogeneous request.

### Weekend sessions are fewer, but heavier

Per-session prompt tokens rise from roughly 1.2M to 1.7M on weekdays to 1.9M to 2.4M at the weekend. Fewer sessions, but more ambitious ones, which reads as developers attempting larger work when nobody is interrupting them.

Chat workloads show the opposite pattern, where the longer sessions fall on weekdays.

### Per session

Table 4

Median, upper percentiles, and mean by metricEach metric uses its own logarithmic scale with the median, P75, P90, and mean printed directly. Session duration is the most skewed row, with a mean 14.9 times its median.metricrow-local log distributionmean / medianUser turnsmed 3mean 6.1P75 7P90 152.0xLLM callsmed 15mean 40.6P75 42.8P90 100.52.7xTool invocationsmed 13mean 43.6P75 45.6P90 111.43.4xSession duration (min)med 4.2mmean 62.6mP75 39.5mP90 177.8m14.9x

Per-session metrics are heavily right-skewed. Session duration has a median of 4.2 minutes against a mean of 62.6, a 14.9 times ratio.

### Per turn

Table 4

Median, upper percentiles, and mean by metricEach metric uses its own logarithmic scale with the median, P75, P90, and mean printed directly. Turn duration is the most skewed row, with a mean 6.3 times its median.metricrow-local log distributionmean / medianLLM callsmed 4.5mean 6.6P75 7.9P90 15.91.8xTool invocationsmed 4mean 7.6P75 7.9P90 212.0xPrompt tokensmed 227.6Kmean 582.5KP75 654KP90 1.5M2.6xCached tokensmed 217.2Kmean 545.3KP75 621.7KP90 1.4M2.5xCompletion tokensmed 1.9Kmean 4KP75 4.6KP90 9.2K2.1xTurn duration (s)med 63.4smean 396.3sP75 163sP90 392.1s6.3x

Taken from Table 4. Section 4.2 of the paper states a median turn of 3 LLM calls, 3 tools and 160.2K prompt tokens, which disagrees with its own table; Figure 6’s annotation reads 4.5, so the table is used here.

Per-turn metrics are also right-skewed, with turn duration showing a 6.3 times mean to median ratio and prompt tokens a 2.6 times ratio.

### Turns per session

Figure 4a

Distribution of User turns per sessionTurns: 3 median at the 50th percentile0.00.20.40.60.81.0CDF of sessions1101001KUser turns per session3 median

Median three turns per session, with a tail reaching several hundred.

### Session duration

Figure 4b

Distribution of Session durationDuration: 4.2min at the 50th percentile0.00.20.40.60.81.0CDF of sessions100ms10s10min6h30dSession duration4.2min

Median session duration is 4.2 minutes, with a persistent tail extending past a day.

### Calls per session

Figure 4d

LLM calls, Tool calls by Calls per sessionLLM calls: 19 at the 50th percentile. Tool calls: 20 at the 50th percentile0.00.20.40.60.81.0CDF of sessions1101001K10KCalls per session1920

- LLM calls
- Tool calls

Figure 4d annotates 19 and 20 without labelling them as medians; Table 4 gives per-session medians of 15 and 13.

LLM calls and tool calls per session track each other closely. Figure 4d annotates 19 and 20, while Table 4 reports per-session medians of 15 LLM calls and 13 tool invocations.

### Tokens per turn

Figure 4e

Prompt, Cached, Completion by Tokens per turnPrompt: 228K at the 50th percentile. Cached: 217K at the 50th percentile. Completion: 1.9K at the 50th percentile0.00.20.40.60.81.0CDF of turns1101001K10K100K1M10M100MTokens per turn228K217K1.9K

- Prompt
- Cached
- Completion

The same asymmetry as a single call, multiplied by the length of a turn.

A turn sends a median of 228 thousand prompt tokens, of which 217 thousand are already cached, and receives about 1.9 thousand completion tokens.

Even the shape of a turn is skewed. The median turn triggers 4.5 model calls, but at P90 it takes 15.9 calls, 21 tool invocations and over a million prompt tokens. A minority of complex turns dominates both execution time and token consumption.

## Six shapes of a turn

Each turn is a workflow generated on the spot from the task in front of it. Clustering them by tool composition, call depth and token consumption produces six recurring shapes.

### Turn workflow archetypes

Table 5

Deep-loop read

9 LLM calls

30.5%

7 tool batches, read-heavy exploration

LLM-only

1 LLM call

20.2%

No tools, pure reasoning

Multi-cycle edit

5 LLM calls

19%

Read, edit, then build

Multi-cycle other

4 LLM calls

13.2%

Read-dominant, little modification

Deep-loop with failures

36 LLM calls

9.1%

34 batches, retry loops

Deep-loop run

7 LLM calls

8.1%

Terminal-heavy

Bar length is each category's share of all turns. Median LLM calls per turn shown at the right.

Deep-loop read accounts for 30.5 percent of turns, LLM-only 20.2 percent, multi-cycle edit 19.0 percent, multi-cycle other 13.2 percent, deep-loop with failures 9.1 percent and deep-loop run 8.1 percent.

The largest group is exploration: 30.5% of turns are repeated file retrieval, symbol lookup and repository navigation, gathering context before touching anything. At the other end, 20.2% of turns call no tools at all and are pure reasoning.

Between them sits the ordinary engineering loop: read, modify, build, read the errors, modify again.

9.1% of turns

### Failure is not an error path. It is a workload.

A turn that hits a failed build or a missing dependency often triggers additional reasoning, retries and tool invocations, and the context window can grow with accumulated error output as it goes into the prompt.

- **LLM calls**: 36against a per-turn median of 4.5
- **Compute**: up to 4xamplification, as the paper states it

Takeaway 4

Coding-agent workflows are highly heterogeneous, and iterative retry workflows can amplify compute by up to four times. Scheduling has to reason about workflow progress, not treat every turn as an equivalent request.

## >275:1

The median call sends 68K prompt tokens and receives 247 back. 88% of calls produce under a thousand output tokens. For comparison, production chat traces report a median prompt of 750 tokens and a median completion of 105.

This is not a generation workload wearing a different hat. The cost is almost entirely on the input side, which is why the paper calls KV-cache reuse the critical serving lever.

Takeaway 5

Coding-agent workloads are far more token-intensive than chat traces, and a large share, 28%, of prompt tokens originates from tool-call results.

### Tokens per LLM call

Figure 10

Prompt tokens, Cached tokens, Completion tokens by Tokens per LLM callPrompt tokens: 68K at the 50th percentile. Cached tokens: 63K at the 50th percentile. Completion tokens: 247 at the 50th percentile0.00.20.40.60.81.0CDF of LLM calls1101001K10K100K1MTokens per LLM call68K63K247

- Prompt tokens
- Cached tokens
- Completion tokens

Prompt and cached tokens are nearly the same distribution. That gap, small as it looks here, is the only part of the prompt that has to be computed.

Prompt tokens have a median of 68 thousand per call, cached prompt tokens 63 thousand, and completion tokens only 247. The input to output ratio exceeds 275 to 1.

### Where the prompt comes from

Figure 11

Proportional compositionConversation history is the largest share at 48%. The full composition is Conversation history 48%, Function-call messages 28%, System prompt 14%, Repo instructions and context 10%.Conversation history: 48%Function-call messages: 28%System prompt: 14%Repo instructions and context: 10%Conversation history: 48%. Accumulated conversational contextConversation history48%Accumulated conversational contextFunction-call messages: 28%. Tool-call messages and resultsFunction-call messages28%Tool-call messages and resultsSystem prompt: 14%. Static instructionsSystem prompt14%Static instructionsRepo instructions and context: 10%. Retrieved repository materialRepo instructions and context10%Retrieved repository material

Three quarters of the context window is the agent’s own prior reasoning and its own tool output. The system prompt is 14 percent, repository instructions and other context the remaining 10.

Conversation history contributes 48 percent of prompt tokens, function-call messages 28 percent, the system prompt 14 percent, and repository instructions and other context the remaining 10 percent.

Takeaway 6

Agentic sessions are overwhelmingly LLM-bound, but time and token contributions are inverted. Inference takes 85.4% of wall-clock time yet contributes 48% of prompt tokens; tools take 4.7% of the time yet contribute 28% of the tokens.

### Time and tokens point opposite ways

Inference owns the clock but contributes 48% of prompt tokens. Tools take 4.7% of the time yet inject 28%. The paper’s reading: model-latency work helps almost every session, while tool-system work only helps the minority dominated by long-running commands.

LLM execution

85.4%of wall-clock time

48%of prompt tokens

Tool execution

4.7%of wall-clock time

28%of prompt tokens

Shares of **non-idle** wall-clock time, from Takeaway 6. Counting the whole session, the median multi-turn session is 80.1% user idle, and the median inference share is 13.7%.

### Inference spread across models

Figure 9

Categories ranked by share16 categories are ranked by share. Model A leads at 23.7%, with smaller categories forming a long tail.Model A: 23.7%Model A23.7%Model B: 16%Model B16%Model C: 13.3%Model C13.3%Model D: 7.4%Model D7.4%Model E: 6.6%Model E6.6%Model F: 6.5%Model F6.5%Model G: 5.5%Model G5.5%Model H: 3.9%Model H3.9%Model I: 2.9%Model I2.9%Model J: 2.6%Model J2.6%Model K: 2.5%Model K2.5%Model L: 2.4%Model L2.4%Model M: 1%Model M1%Model N: 0.8%Model N0.8%Model O: 0.6%Model O0.6%Others: 4.4%Others4.4%

More than 27 models in production during a single week. The names are withheld in the source; the shape of the distribution is not.

The top three models account for about 53 percent of all invocations, with the leading model alone responsible for 23.7 percent. Model names are anonymized in the paper.

## The cache is not a request property.
 It is a session property.

Prefix caching is a critical serving lever in this workload, and its lifecycle is governed by session structure rather than by anything the serving system can see in a request.

### What a boundary costs

Figure 14

Cache hit rate before and after a boundaryWithin a turn the cache hit rate holds around 87 to 91 percent. Crossing a turn boundary on the same model drops it from 81 to 55 percent. Crossing one with a model switch drops it from 75 to 8 percent.0255075100+487%91%Within a turnsame model-2681%55%Turn boundarysame model-6775%8%Turn boundarymodel switchAvg cache hit rate (%)

Last call beforeFirst call after

The step is the finding. Staying inside a turn preserves high cache reuse. Crossing out of one does not.

Within a turn cache hit rate holds at 87 to 91 percent. A turn boundary on the same model drops it 26 points, from 81 to 55. A turn boundary with a model switch drops it 67 points, from 75 to 8.

Inside a turn, prefix caching works almost perfectly. Each call extends the prompt by a small amount and preserves everything before it, so the median call arrives with 63K of its 68K prompt tokens already cached. Across all calls the median hit rate is 98%.

That number hides a bimodal distribution. Roughly 10% of calls see low reuse, below a 20% hit rate, reflecting cold-start calls with minimal prefix to reuse. The paper identifies three structural events that produce those cold starts, none of which a request-scoped scheduler can anticipate.

Takeaway 7

Prefix caching is high overall, a median of 98%, and follows a predictable trajectory within a turn: 45% on the cold-start call, 86% by the second, and a 92 to 94% plateau from the third onward.

### One. The turn boundary

When a turn ends, the user goes away to read, think, or do something else. The gap that follows is long relative to the seconds between calls inside a turn, and the shape of the data is the signature of a time-based eviction policy at the serving system: the entry is likely gone before the next turn arrives. The first call of the next turn lands on a cache that is **26 points colder**.

Takeaway 8

Turn boundaries degrade absolute cache hit rates by 26 points on average, primarily through time-based eviction during inter-turn idle periods.

### Two. The model switch

A KV cache built for one model’s weights cannot be read by another, so a switch does not degrade the cache, it deletes it. Switches touch 6.4% of sessions and are mostly reactive: the non-success rate before a switch is 36% against an 8% baseline, so they are usually a response to errors or rate limiting.

The first call after a switch averages an 8% hit rate. That is a cold start, paid on top of the eviction loss the boundary already caused.

Takeaway 9

Model switches are mostly reactive to rate limiting and compound a turn boundary into near-total cache loss. Pinning sessions to one model, and staging the target model’s cache before an unavoidable switch, are the available defences.

### A turn warms its own cache in two calls

Figure 13b

Cache hit rate by LLM call position within a turnThe first LLM call reuses 45 percent of its prefix. The second call jumps to 86 percent, and calls three through ten sit on a flat plateau near 92 percent as the cache warms.0%20%40%60%80%100%Cache hit rate12345678910LLM call position within turnplateau near 92%45%86%

Each successive call extends the prefix by a small footprint, preserving all prior cached state. Plotted from the figure’s own markers, which sit at 91.5 to 92.3%; the paper’s prose rounds this to 92 to 94%.

Cache hit rate starts at 45 percent on the first call of a turn, jumps to 86 percent on the second, and then sits on a flat plateau near 92 percent from the third call onward.

### Cache survival against idle time between turns

Figure 15

Cache hit rate (%) by Idle time between turnsThe median starts at 94%, remains at 95% through 30s-2m, falls to 70% at 2-10m, and reaches 0% by >1h.<1s: median 94%, interquartile range 42% to 99%1-5s: median 96%, interquartile range 61% to 99%5-30s: median 96%, interquartile range 77% to 99%30s-2m: median 95%, interquartile range 70% to 99%2-10m: median 70%, interquartile range 2% to 97%10m-1h: median 0%, interquartile range 0% to 17%>1h: median 0%, interquartile range 0% to 6%0%20%40%60%80%100%Cache hit rate (%)<1s1-5s5-30s30s-2m2-10m10m-1h>1hIdle time between turns

A plateau, then a cliff between roughly two and ten minutes. That shape is the signature of a time-based eviction policy meeting a user who stepped away. Bars show the interquartile range read from the paper’s box plots.

Cache hit rate holds around 94 to 96 percent for idle gaps under two minutes, drops to a median of 70 percent between two and ten minutes, and collapses to near zero beyond ten minutes.

### Distribution of per-call cache hit rate

Figure 13a

Distribution of Cache hit rate (%)Cache hit rate plotted against Cache hit rate (%).0.00.20.40.60.81.0CDF of LLM calls020406080100Cache hit rate (%)

Two populations, not one. The left mode is cold-start calls with minimal prefix to reuse.

The distribution of cache hit rate is bimodal: roughly 10 percent of calls see low reuse below a 20 percent hit rate, while over 80 percent of calls exceed a 90 percent hit rate.

None of this is visible from inside a single request. Scheduling, admission control and cache management are typically performed at the granularity of individual requests rather than workflows.

That is the argument for making the KV cache a **session-aware schedulable resource** rather than a per-request optimization, and it is what the idle-time section turns into something predictable.

## The third reset is self-inflicted

A long session eventually pushes its prompt toward the model’s context limit. The agent responds by compacting: it rewrites the prompt, summarizing or dropping older messages to buy room to continue.

That rewrite lands on the prefix. The rewritten prompt shares little prefix with what came before, so the cache resets as thoroughly as it would on a model switch, except this time the serving system did it to itself while managing its own context window.

### Where compaction fires

Figure 17

Share of events (%) by Pre-compaction context utilization (% of model limit)The distribution is multi-modal rather than centered on one trigger point. Distinct local peaks appear near 51%, 65%, 81%, 99%.0.1% to 1.9%: 0.1% of events2.1% to 3.9%: 0.2% of events4.1% to 5.9%: 0.3% of events6.1% to 7.9%: 0.6% of events8.1% to 9.9%: 0.7% of events10.1% to 11.9%: 0.9% of events12.1% to 13.9%: 0.9% of events14.1% to 15.9%: 0.9% of events16.1% to 17.9%: 0.9% of events18.1% to 19.9%: 0.8% of events20.1% to 21.9%: 1.9% of events22.1% to 23.9%: 1.2% of events24.1% to 25.9%: 1% of events26.1% to 27.9%: 1.2% of events28.1% to 29.9%: 0.7% of events30.1% to 31.9%: 0.7% of events32.1% to 33.9%: 0.7% of events34.1% to 35.9%: 0.7% of events36.1% to 37.9%: 0.6% of events38.1% to 39.9%: 0.6% of events40.1% to 41.9%: 0.5% of events42.1% to 43.9%: 0.5% of events44.1% to 45.9%: 0.5% of events46.1% to 47.9%: 0.4% of events48.1% to 49.9%: 5% of events50.1% to 51.9%: 6.6% of events52.1% to 53.9%: 3.9% of events54.1% to 55.9%: 2.6% of events56.1% to 57.9%: 1.6% of events58.1% to 59.9%: 1.1% of events60.1% to 61.9%: 0.8% of events62.1% to 63.9%: 4.3% of events64.1% to 65.9%: 9% of events66.1% to 67.9%: 7.2% of events68.1% to 69.9%: 4% of events70.1% to 71.9%: 2.5% of events72.1% to 73.9%: 1.8% of events74.1% to 75.9%: 1.6% of events76.1% to 77.9%: 1.8% of events78.1% to 79.9%: 1.9% of events80.1% to 81.9%: 6.3% of events82.1% to 83.9%: 4.7% of events84.1% to 85.9%: 2.3% of events86.1% to 87.9%: 1.6% of events88.1% to 89.9%: 1.5% of events90.1% to 91.9%: 1.1% of events92.1% to 93.9%: 1% of events94.1% to 95.9%: 0.9% of events96.1% to 97.9%: 1.1% of events98.1% to 99.9%: 7.3% of eventsmedian 66%0%2%4%6%8%10%Share of events (%)0%20%40%60%80%100%Pre-compaction context utilization (% of model limit)

Not one threshold but several. Coding agents appear to trigger compaction at different utilization thresholds for different models, and even a single model shows multiple distinct trigger points.

Pre-compaction context utilization is multi-modal, with pronounced peaks near 50 percent, 65 to 66 percent, 80 percent and close to 100 percent of the model's context limit.

Takeaway 10

Compaction affects 7.8% of sessions, typically dropping prompt tokens by over 70% and cache hit rate by 67%. Incremental, prefix-preserving compaction could keep part of the cache alive.

Compaction concentrates in the heaviest sessions. The 7.8% of sessions that compact at least once account for:

- **of all sessions**: 7.8%
- **of all tokens**: 44.2%
- **of all LLM calls**: 37.1%
- **of all tool calls**: 38.9%

Table 6

### Time on the critical path

Figure 18

Compaction time by Share of turn time (%)Compaction time: 22% at the 50th percentile020406080100CDF of events (%)010203040Share of turn time (%)22%

Compaction is a full LLM call: a long prefill over the history being summarized, then a decode to write the summary.

The median compaction event consumes about 22 percent of the turn's total execution time, with P90 near 34 percent.

### Prompt tokens dropped

Figure 19

Distribution of Token drop (%)Token drop: 72.8% at the 50th percentile0.00.20.40.60.81.0CDF of events30405060708090100Token drop (%)72.8%

Aggressive when it fires. 6.1% of events drop 90% or more of the prompt.

The median compaction event drops 72.8 percent of prompt tokens, with the middle half of events removing between 58 and 81 percent.

### Cache hit rate destroyed

Figure 20

Cache drop by Cache hit rate drop (%)Cache drop: 66.1% at the 50th percentile0.00.20.40.60.81.0CDF of events020406080100Cache hit rate drop (%)66.1%

21% of compaction events erase 99% or more of the cache hit rate. This is a cold start in all but name.

The first call after compaction sees a median cache hit rate drop of 66.1 percent. In 34.3 percent of events the drop erases 90 percent or more.

The sequence is the problem. A session explores deeply, fills its context window, triggers compaction, loses nearly all cached state, and then rebuilds it from scratch, paying both higher latency and higher cost at precisely the moment the task has become most complex. Among long-context sessions, those with prompts over 100K tokens, the rate rises to 22.6%.

## The other half of the loop

More than forty tools are available. Eleven of them account for over ninety percent of all invocations, and the ones that fail most are not the ones that fail cheapest.

### What the agent actually calls

Figure 21; §7.1

Categories ranked by share16 categories are ranked by share. get_file leads at 35%, with smaller categories forming a long tail.get_file: 35%get_file35%run_command_in_terminal: 17%run_command_in_terminal17%replace_string_in_file: 9.8%replace_string_in_file9.8%code_search: 8.1%code_search8.1%run_build: 4.9%run_build4.9%file_search: 4.6%file_search4.6%apply_patch: 3%apply_patch3%create_file: 2.9%create_file2.9%update_plan_progress: 2.3%update_plan_progress2.3%multi_replace_string_in_file: 2.2%multi_replace_string_in_file2.2%get_errors: 1.9%get_errors1.9%edit_file: 1.3%edit_file1.3%get_files_in_project: 0.8%get_files_in_project0.8%get_symbols_by_name: 0.8%get_symbols_by_name0.8%get_projects_in_solution: 0.7%get_projects_in_solution0.7%Others: 4.6%Others4.6%

File retrieval is the largest category, at 35%.Read and searchMutateExecute

get_file accounts for 35 percent of all tool invocations, run_command_in_terminal 17 percent and replace_string_in_file 9.8 percent. The top eleven tools exceed 90 percent of invocations.

### Tool calls against LLM calls, by duration

Figure 22; §7.1

Tool call, LLM call by DurationTool call: 166ms at the 50th percentile. LLM call: 5.3s at the 50th percentile0.00.20.40.60.81.0CDF of calls1ms100ms10s10min7dDuration166ms5.3s

- Tool call
- LLM call

The median LLM call runs 5.3 s against 166 ms for the median tool call. The tool curve’s long right tail is where builds and terminal commands live.

The median tool call takes 166 milliseconds while the median LLM call takes 5.3 seconds. Tool duration has a mean of 16.7 seconds, roughly one hundred times its median.

### Failures are generally slower, and failed builds are the clearest context-expensive exception

- **success rate for run_command, run_build and edit_file, against close to 100% for reads and searches**: 73%
- **longer at P95 for a failed run_command_in_terminal than a successful one**: 48x
- **more prompt tokens injected by a failed build than a successful one, which returns a median of about 60**: 7-8x

Takeaway 11

Tool usage is concentrated and heterogeneous. Read-heavy tools complete fast and succeed nearly universally, while execution tools dominate the tail and fail more often, extending dependency chains and the time a session holds its resources.

### Agents batch tools, but barely

93% of tool batches contain a single invocation. Among the rest the median width is 2 and 87.5% hold at most three, though the tail reaches 108 concurrent calls.

Parallelism is concentrated in read-only operations. Writes and terminal commands mutate shared state, so they are rarely parallelized. Since information gathering fills so much of a turn, there is room to batch more reads at no consistency risk.

Takeaway 12

Tool execution is more parallel than LLM execution but remains largely sequential: 93% of batches invoke a single tool, and most parallel batches contain only two or three read-only operations.

### How much tool time hides behind inference

Figure 28

<50ms99%21% of batches

50-500ms100%46% of batches

0.5-5s76%23% of batches

5-30s35%8% of batches

30s+5%3% of batches

Short batches are almost entirely shadowed by an active LLM call. Batches over thirty seconds are almost entirely exposed.

By count, overlap looks like a solved problem: 97% of tool batches run at least partly inside an inference window.

By wall-clock time it hides 7.7%. The remaining 92% sits on the critical path, because the handful of long builds and terminal commands that dominate total tool time are precisely the ones nothing is running alongside.

Takeaway 13

Tool and LLM overlap is pervasive by count but hides only 7.7% of aggregate tool wall-clock time. The long tail of long-running tools dominates total tool time, is largely un-overlapped, and drives the latency users actually feel.

## Five kinds of developer

Linking sessions through anonymized user identifiers splits the developer population into five behavioural groups. Readers are the largest group, deep-loop users the most resource-intensive, and chat-only users the lightest.

### Population share against per-turn token consumption

Table 7

Per-turn token intensity and population share by user archetypeDeep-loop users are only 9.2 percent of users but consume 1.1M tokens per turn. Chat-only users consume 23K. This creates a roughly 50x range, while marker size shows that the highest-intensity group remains a small share.10K100K1M2MTokens per turn (log scale)marker size = population share50x token rangeReaders41.7% / 203KCoders30.4% / 417KTerminal users11.0% / 213KDeep-loop users9.2% / 1.1MChat-only users7.6% / 23K

Marker area encodes share of the user population. Position encodes tokens per turn, on a log axis.

Readers make up 41.7 percent of users at 203 thousand tokens per turn. Deep-loop users make up 9.2 percent at 1.1 million tokens per turn, while chat-only users make up 7.6 percent at 23 thousand. The spread across archetypes is 50 times.

ArchetypeWhat they doTokens / turn

### Readers

203K

41.7% of users · 6 turns per user · 4.8 tools/turn

Exploring unfamiliar codebases, looking up API signatures, gathering context before deciding. Fast, stateless, cheap to cold-start.

203K

### Coders

417K

30.4% of users · 50 turns per user · 6.2 tools/turn

The most engaged group by session volume. The full engineering loop: gather context, modify code, validate via build or test.

417K

### Terminal users

213K

11% of users · 7 turns per user · 4 tools/turn

Command latency swings from near-instant to minutes-long builds, creating unpredictable idle patterns that complicate scheduling.

213K

### Deep-loop users

1.1M

9.2% of users · 6 turns per user · 20 tools/turn

Large refactors, cross-file migrations, long debugging runs. Few sessions, but each turn generates substantial serving load.

1.1M

### Chat-only users

23K

7.6% of users · 2 turns per user · 0 tools/turn

The lightest workload on the platform, closer to a traditional chatbot interaction than to an agentic coding workflow.

23K

The cost of a cache miss varies by more than an order of magnitude across these groups. For a deep-loop user, one eviction means re-prefilling a median 1.1M tokens. The identical event for a chat-only user costs 23K.

A uniform eviction timeout therefore imposes a disproportionate latency tax on the most resource-intensive user segments. Container lifecycle has the same asymmetry: coders and terminal users accumulate real state, modified files, running processes and build artifacts, while readers can be cold-started with negligible overhead.

Takeaway 14

User archetypes span a 50x range in per-turn token consumption, making uniform resource policies suboptimal. Archetype-aware SLOs can cut tail latency for power users while freeing memory in aggregate.

### Sessions and turns per user

Figure 30

Sessions / user, Turns / user by Per userSessions / user: 2 at the 50th percentile. Turns / user: 11 median at the 50th percentile0.00.20.40.60.81.0CDF of users1101001KPer user211 median

- Sessions / user
- Turns / user

Most people use it lightly. A small fraction of highly active developers accumulate hundreds of turns.

The median user runs two sessions and eleven turns during the week, while P90 reaches eight sessions and 74 turns.

### Total tokens per user

Figure 31

Prompt tokens, Completion tokens by Total tokens per userPrompt tokens: 3.2M at the 50th percentile. Completion tokens: 33K at the 50th percentile0.00.20.40.60.81.0CDF of users10010K1M100MTotal tokens per user3.2M33K

- Prompt tokens
- Completion tokens

Two orders of magnitude between prompt-token and completion-token totals, at the median and at P90 alike.

Median prompt token consumption is 3.2 million per user against 33 thousand completion tokens, with P90 reaching 38 million prompt tokens.

## Idle time is bimodal, and that is the opportunity

The loop alternates between GPU-bound inference and CPU-bound tool execution, so both resources spend time allocated and unused. The gaps come in two sizes, and only one of them is worth acting on.

### Idle duration, inside a turn against across a boundary

Table 8

ResourceIntra-turnCross-turn

Container

Elapsed time between two consecutive tool invocations.

5.8s

P95 44s

4.1min

P95 90min

KV cache

Elapsed time between two consecutive LLM calls.

1.2s

P95 37s

2.9min

P95 75min

Over 90% of idle intervals are intra-turn and last seconds, too short to pay back the cost of reclaiming anything. The 8 to 9% that cross a turn boundary last two orders of magnitude longer.

### User idle between turns

Figure 32b

Distribution of User idle timeUser idle: 25.2min at the 50th percentile0.00.20.40.60.81.0CDF of sessions10ms1s1min1h1d30dUser idle time25.2min

The median user idle gap between turns is 25.2 minutes. Claude's documented default cache retention is five.

The median idle gap between turns is 1512 seconds, about 25 minutes, with a tail extending beyond a day.

### A turn boundary says a session may be reclaimable. It does not say for how long.

Reclaim too early and the next turn pays a reload. Reclaim too late and the memory sits idle. So the authors train a small model that, at each boundary, emits a survival curve: the probability the session stays idle longer than _t_.

That shape lets an operator choose an operating point without retraining, and refine it for free as time passes, since the conditional probability is just a ratio of two points on the same curve.

- **Model**: 12 LightGBM quantile regressors
- **Size**: ~2 MB
- **Inference**: <3 ms per boundary
- **ROC-AUC at 60s**: 0.73, against 0.58 for a previous-gap heuristic and 0.5 for always-positive

What the model leans on

Avg idle time so far28.7

Turn index25.6

Prev. idle time11.5

LLM success rate10.7

Turn duration8.5

LLM calls7.6

Figure 33a · top 6 of 11 · session-level features in accent

### Pointwise accuracy decays. Captured idle time does not.

Figure 33b

Idle predictor quality as time elapses after a turn boundaryPointwise accuracy falls from 81 percent to 42 percent and F1 falls from 89 percent to 25 percent between 30 seconds and 30 minutes. Yet the predictor still captures 86 to 90 percent of total idle time, so it remains useful for resource reclamation even when exact idle duration is uncertain.0%25%50%75%100%Share30s1m2m5m10m15m30mElapsed after turn boundary (log time)captured idle 86.5%F1 25.2%accuracy 42.4%

This gap is the whole result. The model cannot say how long a session will idle, but it reliably knows the session will idle long enough to be worth reclaiming, which is the question that makes reclamation actionable.

As time elapses after a turn boundary, accuracy falls from 81 percent at 30 seconds to 42 percent at 30 minutes and F1 falls from 89 percent to 25 percent, while the share of total idle time correctly captured stays between 86 and 90 percent throughout.

Takeaway 15

Intra-turn idle periods are short and occur during autonomous execution. Cross-turn idle periods are minutes long because a human stepped away. Turn boundaries are therefore the natural trigger for container hibernation and KV-cache offloading.

The prediction is actionable even without control of the backend. Cache retention is time-bounded, five minutes by default on Claude models, so a session idling past that window is recomputed regardless of when its next turn actually arrives. When the predictor says the idle gap will straddle that cutoff, a provider can issue one cheap keep-alive just before the deadline and skip the full recompute entirely.

## What changes downstream

These findings challenge the assumptions underneath current LLM-serving systems. The paper’s answer is agent-native infrastructure: a scheduler that knows which session a request belongs to, and where in that session it sits.

- **Retention priority§8.3**: Deep-loop and coder sessions should receive higher KV-cache retention priority. A single miss costs a deep-loop user a median 1.1M token re-prefill, against 23K for a chat-only user.
- **Eviction and container lifecycle§8.3**: Chat-only and reader sessions can be evicted after short idle timeouts with no meaningful latency penalty. Terminal and coder users hold real container state and need checkpointing rather than termination.
- **Capacity planning§8.3**: Per-user fair-share policies must account for the 50x token gap between chat-only and deep-loop users, to avoid both starving intensive users and over-provisioning for light ones.
- **Session-to-model pinning§5.4**: Pinning a session to one model preserves cache continuity. When a switch is unavoidable, stage the target model's cache in advance rather than paying a synchronous cold start.
- **Incremental compaction§6**: Compaction rewrites the prefix and resets the cache as severely as a model switch. Prefix-preserving or overlapped compaction could maintain partial cache continuity.
- **Turn-boundary reclamation§9.3**: Within a turn, keep the cache resident and the container warm. At a turn boundary, a predicted idle window is long enough to amortize offloading and hibernation.

## Fifteen takeaways

Every finding the authors chose to number, with the section of this page that shows the evidence.

- [01

The agentic loop enforces a strict 1:1 LLM-to-tool coupling. Serving systems must treat LLM calls and their corresponding tool invocations as an inter-dependent pair, not independent requests.

§4.3](#loop)

- [02

87% of LLM calls are agent-initiated. User request arrivals alone do not predict LLM load; capacity planning requires session- or turn-level modeling of autonomous agent execution chains.

§4.3](#loop)

- [03

Agentic execution is predominantly serial. While 63% of multi-call turns exhibit some overlap, concurrency remains shallow (P90 = 1.4) and is concentrated in the middle of turns, creating occasional straggler dependencies and same-session KV-cache contention.

§4.3](#loop)

- [04

Coding-agent workflows are highly heterogeneous, producing large variation in LLM and tool calls and in token consumption. Iterative retry workflows can amplify compute by up to 4x, making workflow-aware scheduling important for efficient serving.

§4.4](#workflows)

- [05

Coding-agent workloads are highly token-intensive: both prompt and completion lengths are substantially larger than those in text-only and multimodal chatbot API traces. A large share, 28%, of prompt tokens originates from tool-call results.

§5.1](#tokens)

- [06

Agentic sessions are overwhelmingly LLM-bound, but time and token contributions are inverted. LLM execution takes 85.4% of wall-clock time yet contributes 48% of prompt tokens, whereas tool calls take only 4.7% of time yet contribute 28% of tokens.

§5.1](#tokens)

- [07

Prefix caching is high overall, a median of 98%, and follows a predictable trajectory within a turn: 45% on the cold-start call, jumping to 86% by the second call, and plateauing at 92 to 94% from the third call onward.

§5.2](#cache)

- [08

Turn boundaries degrade absolute cache hit rates by 26 points on average, primarily via time-based serving-system eviction during inter-turn idle periods.

§5.3](#cache)

- [09

Model switches are mostly reactive to rate limiting and compound a turn boundary into near-total cache loss, a 67 point drop to an average hit rate of 8%. Session-to-model pinning and proactive cache staging on the target model are needed to avoid this added cold-start cost.

§5.4](#cache)

- [10

Context compaction affects 7.8% of sessions overall, typically dropping prompt tokens by over 70% and cache hit rate by 67%, a cache reset comparable in severity to a model switch. Incremental, prefix-preserving compaction strategies could maintain partial cache continuity.

§6](#compaction)

- [11

Tool usage is highly concentrated and heterogeneous. Read-heavy tools complete fast and succeed nearly universally, while execution tools such as run_build and run_command dominate the tail and fail more often; failed invocations take substantially longer, extending dependency chains and workflow resource residency.

§7.1](#tools)

- [12

Tool execution is more parallel than LLM execution but remains largely sequential: 93% of tool batches invoke a single tool, while most parallel batches contain only 2 to 3 read-only operations.

§7.2](#tools)

- [13

Tool and LLM overlap is pervasive by count, 97% of batches run inside an LLM window, but hides only 7.7% of aggregate tool wall-clock time. The long tail of long-running tools dominates total tool time, is largely un-overlapped, and drives session latency.

§7.2](#tools)

- [14

User archetypes span a 50x range in per-turn token consumption, making uniform resource policies suboptimal. Archetype-aware SLOs, with longer cache retention for deep-loop users and aggressive eviction for chat-only and reader sessions, can reduce tail latency for power users while freeing aggregate memory.

§8.3](#users)

- [15

Resource idle time is bimodal. Intra-turn idle periods are short, 5.8s for containers and 1.2s for KV caches, and occur during autonomous agent execution, whereas cross-turn idle periods are minutes long, 243s and 172s, due to user idle time. Turn boundaries therefore provide a natural trigger for container eviction and KV-cache offloading.

§9.1](#idle)

## Blog by

Kiran Hombal

[kstark007.github.io →](https://kstark007.github.io/)

### How this page was made

I didn’t redraw the paper’s figures by eye. The PDF stores every plot as vector geometry, so a script reads the drawing operators, recovers each plot’s axes from its clip rectangle, calibrates both axes against the tick labels, and writes out the real coordinates. Even so, these charts are reconstructions. I don’t have access to the underlying data, only to what the published figures encode, so I have tried to keep them as accurate as the source allows and every figure names the table or figure it came from. For more precise or accurate graphs, please look at the paper itself.

Cite the paper

[Banruo Liu](https://livingshade.github.io/), [Haoran Qiu](https://haoran-qiu.com/), [Íñigo Goiri](https://www.microsoft.com/en-us/research/people/inigog/), [Rodrigo Fonseca](https://www.microsoft.com/en-us/research/people/rofons/), [Ricardo Bianchini](https://www.microsoft.com/en-us/research/people/ricardob/), [Esha Choukse](https://www.microsoft.com/en-us/research/people/eschouks/).
_Agentic Coding in the Wild: Characterizing GitHub Copilot at Production Scale_. [arXiv:2608.00101](https://arxiv.org/abs/2608.00101).

`@misc{liu2026agenticcodingwildcharacterizing,
 title={Agentic Coding in the Wild: Characterizing GitHub Copilot Traces at Production Scale},
 author={Banruo Liu and Haoran Qiu and Íñigo Goiri and Rodrigo Fonseca and Ricardo Bianchini and Esha Choukse},
 year={2026},
 eprint={2608.00101},
 archivePrefix={arXiv},
 primaryClass={cs.AI},
 url={https://arxiv.org/abs/2608.00101},
}`

The research is by Banruo Liu, Haoran Qiu, Íñigo Goiri, Rodrigo Fonseca, Ricardo Bianchini and Esha Choukse. This page is an independent reading of their work: it is not produced, reviewed or endorsed by them, and every figure here is derived from the published PDF.

[Read on arXiv](https://arxiv.org/abs/2608.00101)[Back to the top](#top)

---

## Appendix: the numbers behind the figures

Every figure and table on the page, as data. Transcribed from the paper and rendered from the same constants the page itself uses, so these values and the published charts cannot disagree. The recovered curve geometry for all 23 plots is at `https://kstark007.github.io/blog/agentic-coding-in-the-wild/figure-data.json`.

### Sampled dataset (Table 3)

| label | value |
| --- | --- |
| Sessions | 13.5M |
| User turns | 95.1M |
| Users | 3.2M |
| LLM calls | 760.5M |
| Tool calls | 774.7M |
| Prompt tokens | 44.9T |
| Completion tokens | 39.3B |
| Models / tools | 27+ / 45+ |

### Chatbot versus coding agent (Table 2)

| property | chat | agent |
| --- | --- | --- |
| Calls per interaction | 1 | 15 median, 40+ mean |
| Token asymmetry | Moderate | Extreme: 68K prompt, 247 output |
| State between calls | Stateless, replayed | Tight sequential dependency |
| Resource pattern | GPU only | GPU and CPU/IO alternation |
| Session duration | Seconds | Seconds to minutes or hours |
| Failure handling | Manual retry | Retry loops, 48x P95 blowup |
| Cache sensitivity | Low, requests independent | High, prefix-sharing in the loop |
| Autonomy level | User-driven | Agent-driven, 87% of LLM calls |

### Per session (Table 4)

| metric | median | p75 | p90 | mean | skew | unit |
| --- | --- | --- | --- | --- | --- | --- |
| User turns | 3 | 7 | 15 | 6.1 | 2 |  |
| LLM calls | 15 | 42.8 | 100.5 | 40.6 | 2.7 |  |
| Tool invocations | 13 | 45.6 | 111.4 | 43.6 | 3.4 |  |
| Session duration | 4.2 | 39.5 | 177.8 | 62.6 | 14.9 | min |

### Per turn (Table 4)

| metric | median | p75 | p90 | mean | skew | unit |
| --- | --- | --- | --- | --- | --- | --- |
| LLM calls | 4.5 | 7.9 | 15.9 | 6.6 | 1.8 |  |
| Tool invocations | 4 | 7.9 | 21 | 7.6 | 2 |  |
| Prompt tokens | 227600 | 654000 | 1500000 | 582500 | 2.6 |  |
| Cached tokens | 217200 | 621700 | 1430000 | 545300 | 2.5 |  |
| Completion tokens | 1900 | 4600 | 9200 | 4000 | 2.1 |  |
| Turn duration | 63.4 | 163 | 392.1 | 396.3 | 6.3 | s |

### One turn, step by step (Figure 8)

| kind | label | ms | failed |
| --- | --- | --- | --- |
| llm | LLM call | 9100 |  |
| tool | get_file | 76 |  |
| llm | LLM call | 4000 |  |
| tool | run_build | 28 |  |
| llm | LLM call | 3800 |  |
| tool | get_errors | 30 |  |
| llm | LLM call | 6900 |  |
| tool | run_command | 0 | true |
| llm | LLM call | 4300 |  |
| tool | get_errors | 44 |  |
| llm | LLM call | 5900 |  |
| tool | edit_file | 1000 |  |
| llm | LLM call | 7400 |  |
| tool | run_build | 52 |  |
| llm | LLM call | 12100 |  |
| tool | run_command | 17 |  |

### Turn workflow archetypes

| name | llmCalls | share | description |
| --- | --- | --- | --- |
| Deep-loop read | 9 | 30.5 | 7 tool batches, read-heavy exploration |
| LLM-only | 1 | 20.2 | No tools, pure reasoning |
| Multi-cycle edit | 5 | 19 | Read, edit, then build |
| Multi-cycle other | 4 | 13.2 | Read-dominant, little modification |
| Deep-loop with failures | 36 | 9.1 | 34 batches, retry loops |
| Deep-loop run | 7 | 8.1 | Terminal-heavy |

### User archetypes

| name | share | sessions | turns | toolsPerTurn | tokensPerTurn | tokensLabel | description | detail |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Readers | 41.7 | 2 | 6 | 4.8 | 203000 | 203K | Mostly reads and searches | Exploring unfamiliar codebases, looking up API signatures, gathering context before deciding. Fast, stateless, cheap to cold-start. |
| Coders | 30.4 | 5 | 50 | 6.2 | 417000 | 417K | Balanced read, edit and execute | The most engaged group by session volume. The full engineering loop: gather context, modify code, validate via build or test. |
| Terminal users | 11 | 2 | 7 | 4 | 213000 | 213K | Mostly terminal calls | Command latency swings from near-instant to minutes-long builds, creating unpredictable idle patterns that complicate scheduling. |
| Deep-loop users | 9.2 | 2 | 6 | 20 | 1100000 | 1.1M | Long autonomous loops | Large refactors, cross-file migrations, long debugging runs. Few sessions, but each turn generates substantial serving load. |
| Chat-only users | 7.6 | 1 | 2 | 0 | 23000 | 23K | Pure question and answer, no tools | The lightest workload on the platform, closer to a traditional chatbot interaction than to an agentic coding workflow. |

### Idle time by resource

| resource | definition | intraP50 | intraP95 | crossP50 | crossP95 |
| --- | --- | --- | --- | --- | --- |
| Container | Elapsed time between two consecutive tool invocations. | 5.8 | 44 | 243 | 5424 |
| KV cache | Elapsed time between two consecutive LLM calls. | 1.2 | 37 | 172 | 4500 |

### Where compaction fires

| metric | label | pct |
| --- | --- | --- |
| Sessions | of all sessions | 7.8 |
| Total tokens | of all tokens | 44.2 |
| LLM calls | of all LLM calls | 37.1 |
| Tool calls | of all tool calls | 38.9 |

### Inference spread across models

| name | pct |
| --- | --- |
| Model A | 23.7 |
| Model B | 16 |
| Model C | 13.3 |
| Model D | 7.4 |
| Model E | 6.6 |
| Model F | 6.5 |
| Model G | 5.5 |
| Model H | 3.9 |
| Model I | 2.9 |
| Model J | 2.6 |
| Model K | 2.5 |
| Model L | 2.4 |
| Model M | 1 |
| Model N | 0.8 |
| Model O | 0.6 |
| Others | 4.4 |

### Tool call mix

| name | pct | kind |
| --- | --- | --- |
| get_file | 35 | read |
| run_command_in_terminal | 17 | exec |
| replace_string_in_file | 9.8 | write |
| code_search | 8.1 | read |
| run_build | 4.9 | exec |
| file_search | 4.6 | read |
| apply_patch | 3 | write |
| create_file | 2.9 | write |
| update_plan_progress | 2.3 | read |
| multi_replace_string_in_file | 2.2 | write |
| get_errors | 1.9 | read |
| edit_file | 1.3 | write |
| get_files_in_project | 0.8 | read |
| get_symbols_by_name | 0.8 | read |
| get_projects_in_solution | 0.7 | read |
| Others | 4.6 | other |

### Prompt token composition

| source | pct | note |
| --- | --- | --- |
| Conversation history | 48 | Accumulated conversational context |
| Function-call messages | 28 | Tool-call messages and results |
| System prompt | 14 | Static instructions |
| Repo instructions and context | 10 | Retrieved repository material |

### Cache hit rate at boundaries

| label | sublabel | before | after | delta |
| --- | --- | --- | --- | --- |
| Within a turn | same model | 87 | 91 | 4 |
| Turn boundary | same model | 81 | 55 | -26 |
| Turn boundary | model switch | 75 | 8 | -67 |

### Cache progression within a turn

| call | pct |
| --- | --- |
| 1 | 45 |
| 2 | 86 |
| 3 | 91.5 |
| 4 | 91.9 |
| 5 | 92 |
| 6 | 92.1 |
| 7 | 92.1 |
| 8 | 92.2 |
| 9 | 92.3 |
| 10 | 92.3 |

### Cache survival against idle time

| bucket | median | low | high |
| --- | --- | --- | --- |
| <1s | 94 | 41.7 | 98.5 |
| 1-5s | 95.9 | 60.5 | 98.8 |
| 5-30s | 96.3 | 77.1 | 98.9 |
| 30s-2m | 95.4 | 70 | 98.7 |
| 2-10m | 70.2 | 1.6 | 97.2 |
| 10m-1h | 0 | 0 | 17 |
| >1h | 0 | 0 | 6 |

### Model switches

| Name | Value |
| --- | --- |
| sessionShare | 6.4 |
| errorRateBefore | 36 |
| errorRateBaseline | 8 |
| directions | [object Object],[object Object] |

### Tool and LLM overlap

| bucket | batchShare | overlapped |
| --- | --- | --- |
| <50ms | 21 | 99 |
| 50-500ms | 46 | 100 |
| 0.5-5s | 23 | 76 |
| 5-30s | 8 | 35 |
| 30s+ | 3 | 5 |

### Idle predictor features

| name | weight | scope |
| --- | --- | --- |
| Avg idle time so far | 28.7 | session |
| Turn index | 25.6 | session |
| Prev. idle time | 11.5 | session |
| LLM success rate | 10.7 | turn |
| Turn duration | 8.5 | turn |
| LLM calls | 7.6 | turn |
| Prompt tokens | 2 | turn |
| User cancelled turn | 1.9 | turn |
| Completion tokens | 1.5 | turn |
| Others | 1 | turn |
| Tool failure rate | 1 | turn |

### Idle predictor accuracy

| at | seconds | accuracy | f1 | captured |
| --- | --- | --- | --- | --- |
| 30s | 30 | 80.9 | 88.6 | 88.9 |
| 1m | 60 | 75 | 83.6 | 87.8 |
| 2m | 120 | 67.3 | 75.5 | 86.9 |
| 5m | 300 | 55.9 | 59.2 | 86.7 |
| 10m | 600 | 48.6 | 45 | 86.9 |
| 15m | 900 | 45.5 | 37 | 86.5 |
| 30m | 1800 | 42.4 | 25.2 | 86.5 |

### Idle predictor scalars

| Name | Value |
| --- | --- |
| model | LightGBM quantile regressors on log idle time |
| quantiles | 12 |
| trees | 400 |
| sizeMB | 2 |
| trainSessions | 150000 |
| evalSessions | 50000 |
| inferenceMs | 3 |
| trainHardware | one 16-vCPU AMD EPYC 7763 node, under a minute |
| rocAuc | 0.73 |
| rocAucPrevGapHeuristic | 0.58 |
| rocAucAlwaysPositive | 0.5 |
| capturedIdleLow | 86 |
| capturedIdleHigh | 90 |

### The paper's fifteen takeaways

| n | section | anchor | text |
| --- | --- | --- | --- |
| 1 | 4.3 | loop | The agentic loop enforces a strict 1:1 LLM-to-tool coupling. Serving systems must treat LLM calls and their corresponding tool invocations as an inter-dependent pair, not independent requests. |
| 2 | 4.3 | loop | 87% of LLM calls are agent-initiated. User request arrivals alone do not predict LLM load; capacity planning requires session- or turn-level modeling of autonomous agent execution chains. |
| 3 | 4.3 | loop | Agentic execution is predominantly serial. While 63% of multi-call turns exhibit some overlap, concurrency remains shallow (P90 = 1.4) and is concentrated in the middle of turns, creating occasional straggler dependencies and same-session KV-cache contention. |
| 4 | 4.4 | workflows | Coding-agent workflows are highly heterogeneous, producing large variation in LLM and tool calls and in token consumption. Iterative retry workflows can amplify compute by up to 4x, making workflow-aware scheduling important for efficient serving. |
| 5 | 5.1 | tokens | Coding-agent workloads are highly token-intensive: both prompt and completion lengths are substantially larger than those in text-only and multimodal chatbot API traces. A large share, 28%, of prompt tokens originates from tool-call results. |
| 6 | 5.1 | tokens | Agentic sessions are overwhelmingly LLM-bound, but time and token contributions are inverted. LLM execution takes 85.4% of wall-clock time yet contributes 48% of prompt tokens, whereas tool calls take only 4.7% of time yet contribute 28% of tokens. |
| 7 | 5.2 | cache | Prefix caching is high overall, a median of 98%, and follows a predictable trajectory within a turn: 45% on the cold-start call, jumping to 86% by the second call, and plateauing at 92 to 94% from the third call onward. |
| 8 | 5.3 | cache | Turn boundaries degrade absolute cache hit rates by 26 points on average, primarily via time-based serving-system eviction during inter-turn idle periods. |
| 9 | 5.4 | cache | Model switches are mostly reactive to rate limiting and compound a turn boundary into near-total cache loss, a 67 point drop to an average hit rate of 8%. Session-to-model pinning and proactive cache staging on the target model are needed to avoid this added cold-start cost. |
| 10 | 6 | compaction | Context compaction affects 7.8% of sessions overall, typically dropping prompt tokens by over 70% and cache hit rate by 67%, a cache reset comparable in severity to a model switch. Incremental, prefix-preserving compaction strategies could maintain partial cache continuity. |
| 11 | 7.1 | tools | Tool usage is highly concentrated and heterogeneous. Read-heavy tools complete fast and succeed nearly universally, while execution tools such as run_build and run_command dominate the tail and fail more often; failed invocations take substantially longer, extending dependency chains and workflow resource residency. |
| 12 | 7.2 | tools | Tool execution is more parallel than LLM execution but remains largely sequential: 93% of tool batches invoke a single tool, while most parallel batches contain only 2 to 3 read-only operations. |
| 13 | 7.2 | tools | Tool and LLM overlap is pervasive by count, 97% of batches run inside an LLM window, but hides only 7.7% of aggregate tool wall-clock time. The long tail of long-running tools dominates total tool time, is largely un-overlapped, and drives session latency. |
| 14 | 8.3 | users | User archetypes span a 50x range in per-turn token consumption, making uniform resource policies suboptimal. Archetype-aware SLOs, with longer cache retention for deep-loop users and aggressive eviction for chat-only and reader sessions, can reduce tail latency for power users while freeing aggregate memory. |
| 15 | 9.1 | idle | Resource idle time is bimodal. Intra-turn idle periods are short, 5.8s for containers and 1.2s for KV caches, and occur during autonomous agent execution, whereas cross-turn idle periods are minutes long, 243s and 172s, due to user idle time. Turn boundaries therefore provide a natural trigger for container eviction and KV-cache offloading. |

### Implications stated by the authors

| section | title | body |
| --- | --- | --- |
| 8.3 | Retention priority | Deep-loop and coder sessions should receive higher KV-cache retention priority. A single miss costs a deep-loop user a median 1.1M token re-prefill, against 23K for a chat-only user. |
| 8.3 | Eviction and container lifecycle | Chat-only and reader sessions can be evicted after short idle timeouts with no meaningful latency penalty. Terminal and coder users hold real container state and need checkpointing rather than termination. |
| 8.3 | Capacity planning | Per-user fair-share policies must account for the 50x token gap between chat-only and deep-loop users, to avoid both starving intensive users and over-provisioning for light ones. |
| 5.4 | Session-to-model pinning | Pinning a session to one model preserves cache continuity. When a switch is unavoidable, stage the target model's cache in advance rather than paying a synchronous cold start. |
| 6 | Incremental compaction | Compaction rewrites the prefix and resets the cache as severely as a model switch. Prefix-preserving or overlapped compaction could maintain partial cache continuity. |
| 9.3 | Turn-boundary reclamation | Within a turn, keep the cache resident and the container warm. At a turn boundary, a predicted idle window is long enough to amortize offloading and hibernation. |

### Limitations stated by the authors

| title | body |
| --- | --- |
| No quality signals | Without prompt and response content, infrastructure efficiency cannot be correlated with task completion quality. |
| No server-side view | The traces are client-side. GPU utilization, queue depth, batch size and memory pressure are not observable. |
| Evolving workload | Tools, models and autonomy strategies change weekly. Results held from January to June 2026, but longitudinal tracking is needed. |

### Scalars quoted in prose

| Fact | Value |
| --- | --- |
| agentInitiatedPct | 87 |
| userInitiatedPct | 13 |
| llmCallsPerTurnMean | 6.6 |
| sequentialTurnsPct | 36.7 |
| overlappingTurnsPct | 63.3 |
| parallelismMedian | 1.15 |
| parallelismP90 | 1.4 |
| promptTokensMedian | 68000 |
| cachedTokensMedian | 63000 |
| completionTokensMedian | 247 |
| outputUnder1kPct | 88 |
| inputOutputRatio | 275 |
| chatPromptMedian | 750 |
| chatCompletionMedian | 105 |
| multimodalPromptMedian | 1050 |
| multimodalCompletionMedian | 80 |
| singleTurnSessionPct | 6 |
| multiTurnSessionPct | 94 |
| multiTurnLlmTimePct | 13.7 |
| multiTurnToolTimePct | 2 |
| multiTurnUserIdlePct | 80.1 |
| llmWallClockPct | 85.4 |
| toolWallClockPct | 4.7 |
| cacheHitMedian | 98 |
| cacheLowReuseCallsPct | 10 |
| compactionCallPct | 0.5 |
| compactionSessionPct | 7.8 |
| compactionLongContextPct | 22.6 |
| compactionCountMedian | 1 |
| compactionCountMean | 1.7 |
| compactionCountMax | 40 |
| compactionTriggerMedian | 66 |
| compactionTurnTimeMedian | 22 |
| compactionTurnTimeP90 | 34 |
| compactionTokenDropMedian | 72.8 |
| compactionTokenDropP25 | 58 |
| compactionTokenDropP75 | 81 |
| compactionTokenDropOver90Pct | 6.1 |
| compactionCacheDropMedian | 66.1 |
| compactionCacheErase90Pct | 34.3 |
| compactionCacheErase99Pct | 21 |
| toolDurationMedianMs | 166 |
| toolDurationMeanS | 16.7 |
| toolDurationP90S | 4.4 |
| toolDurationP99S | 79 |
| llmDurationMedianS | 5.3 |
| toolLatencySpread | 320 |
| runCommandMeanS | 68 |
| runBuildMeanS | 78 |
| execSuccessRatePct | 73 |
| failedRunCommandP95Multiple | 48 |
| runBuildSuccessTokens | 60 |
| runBuildFailureMultiple | 7 |
| singleToolBatchPct | 93 |
| parallelBatchMedianWidth | 2 |
| parallelBatchP875 | 3 |
| parallelBatchMax | 108 |
| batchesOverlappedPct | 97 |
| toolTimeHiddenPct | 7.7 |
| toolFailureTurnPct | 9 |
| failureComputeAmplification | 4 |
| containerIdleMedianS | 6.8 |
| kvIdleMedianS | 5 |
| userIdleMedianS | 1512 |
| userIdleMedianMin | 25.2 |
| sessionsPerUserMedian | 2 |
| sessionsPerUserP90 | 8 |
| turnsPerUserMedian | 11 |
| turnsPerUserP90 | 74 |
| promptTokensPerUserMedian | 3200000 |
| completionTokensPerUserMedian | 33000 |
| promptTokensPerUserP90 | 38000000 |
| completionTokensPerUserP90 | 282000 |
| archetypeTokenSpread | 50 |
| weekdayLlmCallsLow | 22 |
| weekdayLlmCallsHigh | 28 |
| weekendLlmCallsLow | 27 |
| weekendLlmCallsHigh | 33 |

## Citing the paper

```bibtex
@misc{liu2026agenticcodingwildcharacterizing,
      title={Agentic Coding in the Wild: Characterizing GitHub Copilot Traces at Production Scale},
      author={Banruo Liu and Haoran Qiu and Íñigo Goiri and Rodrigo Fonseca and Ricardo Bianchini and Esha Choukse},
      year={2026},
      eprint={2608.00101},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={https://arxiv.org/abs/2608.00101},
}
```
