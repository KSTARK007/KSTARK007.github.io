---
title: "The Partly Coherent CXL: A field guide to shared CXL memory"
author: "Kiran Hombal, Jiyu Hu"
authors:
  - name: "Kiran Hombal"
    url: "https://kstark007.github.io/"
  - name: "Jiyu Hu"
    url: "https://jiyuuuhuuu.github.io/"
canonical_url: "https://kstark007.github.io/blog/one-memory-many-machines/"
date_published: "2026-08-25T09:00:00-05:00"
date_modified: "2026-10-10T09:00:00-05:00"
description: "What shared CXL memory is, why hardware coherence covers only a sliver of it, and how to share data on it anyway: a general-audience walk from the memory wall to our lab's Megalon (OSDI '26) and Prism (SOSP '26)."
based_on_papers: "Megalon: Efficient Data Sharing for Partly Coherent CXL Memory (OSDI 2026); Disk-Based LSMs: An Unexpectedly Good Index for Partly Coherent CXL Memory (SOSP 2026)"
megalon_authors: "Jiyu Hu, Seokjoo Cho, Landon Johnson, Kiran Hombal, Shreesha G. Bhat, Marcos K. Aguilera, Ramnatthan Alagappan, Aishwarya Ganesan"
prism_authors: "Kiran Hombal, Jiyu Hu, Marcos K. Aguilera, Ramnatthan Alagappan, Aishwarya Ganesan"
megalon_artifact: "https://github.com/dassl-uiuc/MEGALON-artifact"
keywords: ["CXL", "Compute Express Link", "shared memory", "cache coherence", "partly coherent memory", "memory disaggregation", "Megalon", "Prism", "LSM tree", "distributed systems"]
---

# The Partly Coherent CXL

*A field guide to shared CXL memory*

A general-audience explainer by [Kiran Hombal](https://kstark007.github.io/) and [Jiyu Hu](https://jiyuuuhuuu.github.io/) of shared CXL memory and of two papers from the DASSL Lab, UIUC: **Megalon: Efficient Data Sharing for Partly Coherent CXL Memory** (OSDI 2026, best-paper nominee) by Jiyu Hu, Seokjoo Cho, Landon Johnson, Kiran Hombal, Shreesha G. Bhat, Marcos K. Aguilera, Ramnatthan Alagappan, Aishwarya Ganesan, and **Disk-Based LSMs: An Unexpectedly Good Index for Partly Coherent CXL Memory** (SOSP 2026) by Kiran Hombal, Jiyu Hu, Marcos K. Aguilera, Ramnatthan Alagappan, Aishwarya Ganesan. The systems and results are the papers'; the simplifications are the authors'.

Canonical HTML version: https://kstark007.github.io/blog/one-memory-many-machines/

---

<a id="tldr"></a>

## TL;DR

CXL 3.0 enables multiple TBs of memory to be shared between multiple hosts, opening new potential for distributed applications such as databases and KV stores. However, it is reported that only a small portion of the shared CXL memory region (hundreds of MBs) can support cross-host cache coherence due to hardware constraints, leaving the remaining TBs of memory non-cache-coherent across hosts.

**Megalon** enables coherently sharing a large number of data objects in the partly coherent CXL memory by utilizing the software coherence approach. It does so efficiently through **split metadata sharing**, which uses the precious coherent region smartly by storing only the performance-crucial coherence metadata.

**Prism** explores how to build a shared index on top of partly coherent CXL in a principled manner. It makes a core observation that the LSM, a data structure originally optimized for disk accesses, is an unexpectedly great fit for CXL indexes. The reason lies in the LSM’s small **updatable surface area**.

- **Papers**: 2

OSDI '26 · SOSP '26

- **Best-paper nominee**: 1

Megalon at OSDI '26

<a id="enter-cxl"></a>

## 1. Intro to CXL

A great new memory technology

**The memory wall.** Server CPUs went from a dozen cores in 2012 to well over a hundred today, yet DRAM capacity per core has been falling for a decade: a CPU cannot simply add memory channels, because each DDR channel takes roughly 200 signal pins. You cannot fix a pin-count problem with software. You need a new wire.

**Compute Express Link (CXL)** is that wire. It is an open standard built on PCIe. A CXL memory device is a box of DRAM on PCIe, and the CPU issues direct memory loads and stores, not I/O operations like a disk. Once mapped, it is just more memory to a program.

### Two ways out of the socket

Sharma et al., CXL survey · PCI-SIG

Bandwidth per signal pin is the whole story: close to **1 GB/s per pin** for the PCIe link against about **0.25** for DDR5, roughly 4× more, and PCIe 6.0 doubles it again. A CPU can afford far more of these narrow links than DDR channels, which is how CXL adds terabytes where the DDR bus cannot. The survey we cite quotes 256 GB/s in its introduction; its own bandwidth section gives the per-direction figure used here.

A diagram comparing a DDR channel, about 200 signal pins for about 51 gigabytes per second, against a CXL link over PCIe, 64 signal pins for about 63 gigabytes per second in each direction.

The price for better scalability is the latency. Local DRAM answers in roughly 110 ns; CXL memory takes two to three times that, about the cost of reaching the _other socket_ of a two-socket server (a NUMA hop), which software tolerates every day. It is still far closer than a remote read over RDMA (microseconds) or an SSD (tens of microseconds).

### Where CXL lands in the hierarchy

Melody (ASPLOS '25); Next Platform

Approximate latency, log scale. Each dot is a point inside a range; the table says which rows are measured and which are textbook orders of magnitude. CXL sits in the long gap between DRAM and the network.

Show the numbers

Where CXL lands in the hierarchy

- Tier · Latency · Note · Basis ·
- L1 cache · ~1 ns · on the core itself · textbook order of magnitude ·
- L2 cache · ~4 ns · private per core · textbook order of magnitude ·
- L3 cache · ~15 ns · shared on the die · textbook order of magnitude ·
- Local DRAM · ~111–117 ns · over the DDR bus · measured on three Melody platforms ·
- CXL memory · ~170–400 ns · about one NUMA hop away · Melody measured 214–394 ns; industry quotes 170–250 ns ·
- RDMA read · ~2–10 µs · network round trip · commonly reported range ·
- NVMe SSD · ~10–100 µs · flash storage · commonly reported range ·

A log-scale ladder of approximate access latencies from L1 cache at about one nanosecond, through local DRAM near 110 nanoseconds, CXL at roughly 170 to 400 nanoseconds, RDMA at microseconds, and NVMe SSDs at tens of microseconds.

<a id="shared-memory"></a>

### CXL 3.0: cross-host sharing

From CXL 1.0 to CXL 3.0, from memory expansion to memory sharing

CXL 1.1 (2019) does _expansion_: one host, more memory. CXL 2.0 (2020) adds switching and _memory pooling_: a rack-level pool carved into segments, each still owned by one host at a time. CXL 3.0 (2022) and its successors (3.2 in 2024, 4.0 in late 2025) add the radical part: **multi-host shared memory**. Several machines map the _same_ region into their address spaces so to share data efficiently over a unified piece of memory.

Now with CXL 3.0 shared memory, databases, key-value stores, and file systems could keep one copy of their data which every host can reach. Accessing shared data can be a single memory operation instead of a trip over the network.

If it sounds too good to be true, it is, due to a catch of CXL 3.0 that prevents data from being shared correctly.

### Three generations, three relationships to memory

CXL Consortium spec releases

Toggle the generations. Expansion gives one host more memory; pooling gives each host its own segment; sharing lets every host map the same region at once. The overlap is the new thing.

An interactive diagram showing CXL 1.1 with one host and one expander, CXL 2.0 with a switch assigning pool segments to individual hosts, and CXL 3.0 with four hosts mapping one shared region simultaneously.

<a id="partly-coherent"></a>

## 2. The catch: partly coherent memory

CXL 3.0 lacks full cross-host cache coherence, and it causes problems...

Background · Cache coherence · expand if new to CPU caches

Most memory loads/stores never reach DRAM. A trip to memory costs about 100 ns, so every CPU keeps recently used data in small, fast, private **caches** and serves most loads/catches most stores from there. Caching creates copies, and copies can go stale: if one CPU changes a value that another has cached, the other’s copy is now wrong.

Inside one machine you never see this, because the hardware does the heavy lifting. **Cache coherence** keeps every cached copy of a location consistent: before a CPU writes, the hardware finds the other copies and invalidates them, so every CPU always sees one coherent view of memory. Software gets that for free. The hardware pays for it in bookkeeping, which grows with the number of caches and the amount of memory tracked.

Now imagine scaling the hardware cache coherence support up to what CXL 3.0 allows: several _machines_, dozens of caches each, sharing _terabytes_. To behave like memory inside one machine, the hardware would have to run coherence across hosts, over PCIe, for every cache line. The vendors are blunt about the arithmetic: AMD, Micron, and Samsung all say the machinery involved stops scaling somewhere between dozens and a few hundred megabytes.

So the hardware is expected to compromise, in what we call the **partly coherent model**, which both of our papers target. The memory splits in two. A **small coherent region**, the _SCR_, is the part that hardware keeps coherent across hosts. A **large non-coherent region**, the _LNR_, is the rest of the memory, where the hardware does nothing about coherence across hosts. Each host’s own cache coherence still works; it just never hears from the others.

### The two regions, side by side

Megalon §2.1 · Tigon, citing AMD

A few hundred MB on a device of several TB: roughly one part in ten thousand. The marker is widened so that it is visible at all. Everything the hardware promises about coherence across hosts happens inside it.

A device of several TB with a coherent region of a few hundred MB: **roughly one part in ten thousand**. The marker is widened to be visible at all; at true scale you could not see it, which is the point.

A long bar representing several terabytes of CXL memory. The hardware-coherent region, a few hundred megabytes, would be far thinner than a pixel; it is drawn as a widened marker at the left edge and shown magnified.

What goes wrong in the LNR without coherence? Suppose Host 1 reads object A and caches it. Host 2 overwrites it with A′. On one machine that write would invalidate host 1’s copy; across machines, in the LNR, _no invalidation is ever sent_. Host 1 reads again, its cache says “I have that,” and it returns the stale value. Silently. Your database just served data that is no longer fresh.

One could simply use the SCR to share data, but a few hundred megabytes shared among many hosts is nothing; the whole point was the terabytes. Rejected. Therefore, we need a better approach to share data coherently in CXL.

### The stale read, step by step

1 / 4 · Host 1 reads A from the LNR

The value drops into host 1’s CPU cache, as every read does.

Host 2’s write reaches the memory, but no invalidation reaches host 1’s cache, so host 1’s next read is answered by its own cache, wrongly.

An animation of two hosts sharing a value in the non-coherent region. Host 1 caches A; host 2 writes A-prime; host 1 reads again and its cache serves the stale A with a warning flag.

<a id="software-coherence"></a>

## 3. A software approach, and how it collapses

Cache coherence can be managed in software, but a naive approach takes a performance hit.

A better idea keeps the _data_ in the vast LNR and small **metadata** in the SCR to track the coherence, where hardware coherence makes the metadata itself trustworthy. We call this approach **software coherence**.

Specifically, each shared object gets a _coherence record_ located in the SCR, think of a version counter plus a lock, and a host checks the record before touching the object; if someone wrote it since the host’s last access, meaning that the host might hold a stale cache, the host issues manual cache flush operations in software and re-reads from CXL. The first figure on the right steps through it.

Next to each object’s coherence record, a shared index lets hosts find each object and its record. We refer to the index and the coherence records together as the metadata. In the Megalon paper, we call this software coherence approach, which keeps _all_ of the metadata in the SCR to track coherence for data in the LNR, **hardware-coherent metadata-based sharing**, **HCMeta** for short. **Tigon** (OSDI ’25), a partitioned database for a multi-host CXL pod, works this way.

### Software coherence, step by step

Megalon §2.2

1 / 4 · Host 1 reads A

Host 1 reads A from the LNR and notes its version from A’s coherence record in the SCR: 0.

A version record per object in the SCR, which hardware keeps coherent; a reader that finds a newer version drops its copy and re-reads. Simplified: the lock, the fences, and the mid-read retry are left out.

An animation of software coherence. Host 1 caches A at version 0; host 2 writes A-prime to the LNR and bumps A's version in the SCR to 1; host 1 checks the SCR, sees 0 does not match 1, invalidates its cached A, and re-reads A-prime from the LNR.

HCMeta works perfectly for Tigon’s workload of occasional cross-partition transactions. But push more data into sharing and a problem surfaces: _the metadata grows with the number of shared objects, but the SCR does not._ So the SCR soon fills up after sharing only a limited number of data objects (roughly in the low millions).

At the cap, HCMeta **unshares** an old object to make room for a new one. Objects start rotating through the tiny window of shareability, and every rotation is expensive: the host needs to wait for an object to be reshared if it is unshared by the owner. We call the rotation _churn_. As the dataset grows, churn cuts throughput sharply, as the second figure on the right shows.

**Summary.** Software coherence lets hosts share data objects in the LNR while keeping them coherent, but HCMeta, which keeps all of its metadata in the SCR, takes a performance hit once the SCR fills up. So our first paper asks: _how can hosts share a huge number of objects when even the metadata is too big for the coherent region?_

### Measure HCMeta collapse

Megalon, Figure 1(c)

- HCMeta, 100 MB SCR
- HCMeta, unlimited SCR

A key-value store using HCMeta, read-only, 100 MB SCR. The unlimited-SCR variant, which simulates an unrealistic SCR not limited to a few hundred MB, stays flat; the real one falls from **15.2 to 1.0 Mops/s** (million operations per second) between 2.4M and 4.8M objects and keeps sinking. For scale: with 40-byte keys HCMeta spends 52 bytes of SCR per object, so 100 MB caps sharing near 1.9M objects.

Show the numbers

Measure HCMeta collapse

- Dataset · HCMeta, 100 MB SCR · Unlimited SCR ·
- 1.2M objects · 15.5 Mops/s · 15.5 Mops/s ·
- 2.4M objects · 15.2 Mops/s · 15.3 Mops/s ·
- 4.8M objects · 1.0 Mops/s · 15.1 Mops/s ·
- 7.2M objects · 0.9 Mops/s · 15.0 Mops/s ·
- 12M objects · 0.7 Mops/s · 14.6 Mops/s ·
- 18M objects · 0.6 Mops/s · 13.8 Mops/s ·

A line chart of throughput versus dataset size. With unlimited SCR, throughput holds near 15 million operations per second. With a realistic SCR, throughput collapses from about 15 to about 1 million operations per second once the dataset passes a few million objects.

<a id="megalon"></a>

Paper one · OSDI 2026 · Best-paper nominee

## 4. Megalon

Share the data. Split the metadata.

Skipped ahead? The setup in brief

CXL lets hosts share terabytes, but reportedly keeps only a small region coherent across hosts (the **SCR**, a few hundred MB); the large non-coherent region (**LNR**) can silently serve stale cached data. A natural fix, **HCMeta**, uses metadata in the SCR to track coherence for data in the LNR through a software approach, but the metadata can grow huge and soon fill up the SCR without even sharing a large number of data objects (~2M). The performance collapses past it. [↑ The partly coherent model](#partly-coherent) · [↑ How HCMeta collapses](#software-coherence)

**Megalon** starts where HCMeta breaks, with one observation: the metadata is two very different things glued together. **The index**, which maps each object’s ID to its location, is _big_ (every object’s key, tens of bytes each) but _cold_: it changes on inserts and deletes, far less often than data writes. **The coherence records** are _tiny_ (a lock bit and a counter, 4 bytes) but _hot_: touched on every write.

HCMeta stuffs both into the SCR. Megalon’s key idea is to **split** them and share each the way its nature demands. The hot, tiny records stay _physically_ shared in the SCR, where hardware coherence makes coherence checks fast; at 4 bytes, about 13× more of them fit than HCMeta’s 52-byte bundles. The big, cold index is _logically_ shared: every host keeps a full **replica** in its local DRAM, of which it has hundreds of gigabytes, roughly 1000× the SCR. A 100 MB SCR that capped HCMeta near 2 million objects lets Megalon share about 25 million.

At first sight, replicating the index recreates the problem: N replicas must now be kept consistent. However, the index is the _cold_ half. It changes rarely, so keeping replicas in sync is cheap, given a mechanism to do it.

### Split metadata sharing

Megalon §3.2, Figure 2

The index moved to where memory is plentiful, saving SCR space for frequently accessed tiny coherence records.

The big, cold index is replicated into each host’s DRAM; only the tiny, hot records occupy the SCR. For the paper’s 40-byte-key example, **52 bytes** of SCR per object becomes **4**.

A diagram of Megalon's split: index replicas in each host's local DRAM point to data objects in the LNR and to small coherence records in the SCR. Occupancy bars compare 52 bytes per object for HCMeta against 4 for Megalon.

That mechanism is a **shared log**: a linearizable, ordered sequence of entries that many parties can _append_ to at the tail and _read_. It is the classic basis for **state machine replication**: replicas that apply the same entries in the same order reach the same state. Megalon keeps the index replicas consistent exactly this way.

Shared logs are usually built on distributed protocols that pass messages, at high cost. Megalon instead follows **Node Replication** (NR), which uses a shared log to build concurrent data structures across NUMA sockets, but places the log in the LNR, where every _host_ reads and appends to it directly, with no message passing.

Only the log’s **head and tail**, on which its correctness depends, live in the SCR beside the coherence records, so they get hardware coherence at almost no SCR cost. To change the index, a host claims the next entry with an atomic compare-and-swap on the tail, writes the entry, and flushes it. Before any index read, a host checks the tail and applies any new entries to its replica.

Deeper dive · techniques built on the log

The log supports two further coherence techniques.

**Dynamic coherence records.** With split metadata sharing, Megalon can share far more objects than HCMeta, but it is still fundamentally limited by the number of coherence records that fit in the SCR. We make another core observation: objects that are only _read_ need no record, since nothing changes under the readers. So Megalon allocates records only for objects that are read and written. Therefore, Megalon can fit an unlimited number of read-only objects, as long as they fit in the LNR. When the SCR fills, Megalon demotes cold objects and reassigns their records, announcing each change through the log. However, churn becomes an appended entry rather than a round trip: about 8× cheaper than HCMeta.

**Dual-path coherence.** With records coming and going, an object can gain or lose its record _while you are reading it_, so the record alone cannot prove your cache is fresh. Hosts therefore also check, at the end of a read, whether the log recorded an allocation event for the object; if so, they flush and retry.

**Other uses of the log.** Since every index change is ordered by the log, Megalon can also keep a host’s private objects in its local DRAM, and cache read copies of hot shared objects there, where access is faster than CXL (paper §3.5).

### A shared log in CXL

Megalon §3.3, §4

Only the head and tail pointers need hardware coherence. The entries sit in the LNR, written with a flush and read past the cache, and order does the rest.

Hosts claim entries with a compare-and-swap on the tail and replay them into their replicas. Ordering without messages; the only coordination is atomic operations on two pointers in the SCR.

A shared log laid out in the non-coherent region with its head and tail pointers in the coherent region. Hosts append entries and replay them into local index replicas.

Against HCMeta, Megalon delivers 15× on read-only workloads with large datasets and 10× at 5% writes once metadata outgrows the SCR. The cost is host DRAM for the index replicas, 7.6% more memory in the 24M-object read-only run.

### Megalon flat where HCMeta collapses

Megalon Figure 6(a)

- HCMeta
- Megalon

5% writes, Zipfian, 200 MB SCR. From 4.8M to 24M shared objects HCMeta churns and collapses while Megalon holds near 17 Mops/s: **10×** at 24M, all thanks to more data being shared through split metadata sharing. [Read the paper](https://dassl-uiuc.github.io/pdfs/papers/megalon.pdf) for more experiments.

Show the numbers

Megalon flat where HCMeta collapses

- Shared objects · HCMeta · Megalon ·
- 4.8M · 16.6 Mops/s · 17.7 Mops/s ·
- 7.2M · 5.7 Mops/s · 17.2 Mops/s ·
- 12M · 2.5 Mops/s · 17.4 Mops/s ·
- 24M · 1.7 Mops/s · 17.4 Mops/s ·

Grouped bars of throughput for 4.8, 7.2, 12 and 24 million shared objects under 5 percent writes. Megalon stays near 17 million operations per second at every size; HCMeta falls from 16.6 to 1.7, a ten times gap at 24 million objects.

<a id="index-problem"></a>

## 5. The index problem

What is the right way to build an index for shared CXL memory?

Shared CXL memory opens the door for a whole range of applications to share data directly: databases, key-value stores, file-system metadata services, analytics engines. Most of them rely on the same building block, an **index** that supports point queries, range queries, and updates. So our second paper asks a simple question: _what is the right way to build an index for shared CXL memory?_

The natural starting point is the software coherence approach from [section 3](#software-coherence): data in the LNR, coherence metadata in the SCR, and a check of the metadata before every access. Can we use it to port existing indexes? We start with two widely used in-memory indexes. The **adaptive radix tree (ART)** looks up a key in O(k) steps for a key of length k, and its nodes are adaptive: they start as a tiny Node4 and grow up to Node256, so in practice ART has many small nodes. The **B+-tree** is the opposite: O(log n) lookups, and a few large, fixed-size nodes with high fan-out. To apply software coherence to either index, we need metadata that lets a host detect when its cached copy of a node may be stale. Luckily, both already have it. Their concurrency control, **optimistic lock coupling (OLC)**, keeps a version number per node that changes whenever the node is updated. We piggyback on the same version numbers to detect stale cached nodes across hosts.

The port is then straightforward. We separate the version numbers from the tree nodes and move them into the SCR, where hardware keeps them coherent; the tree nodes and the key-value pairs stay in the LNR. Before reading a node, a host checks its version number. If it has changed since the host last read the node, the host flushes the stale cache lines and fetches the current data. We call these software-coherent indexes **SC-ART** and **SC-BTree**. Simple enough, right? Not really. It comes with its own problems.

**Problem 1: version numbers overflow the SCR.** Every node needs a version number in the SCR, and as the tree grows, so does the number of version numbers. With 100M keys, ART has ~40M inner nodes; at 8 bytes per version, a 128 MB SCR holds only about 40% of them. The rest spill into the LNR, and now the metadata we rely on to detect stale data can itself be stale. A host must flush a spilled version number on every access and re-read it, even if nothing has changed. Take the SCR away entirely, so that every version number spills, and SC-ART runs about 20× slower than with a 128 MB SCR. Would fewer but larger nodes be an easy fix?

### Problem 1: version numbers overflow the SCR

Prism §3.2, Figure 1

1 / 4 · A small tree: every version number fits

Each node of SC-ART keeps its version number in the SCR. With five nodes, five of the eight slots are used, and a host checks a node’s version there before trusting its cached copy.

Every node of SC-ART keeps a version number in the SCR. As the tree grows, the version numbers outnumber the slots, and the ones that spill into the LNR have to be flushed on every access. The tree and the eight slots are drawn small; the last step gives the paper’s numbers.

An animation of an ART growing from five nodes to thirteen while its version numbers fill eight slots in the coherent region; the five that spill into the non-coherent region are marked as needing a flush on every access.

**Problem 2: bigger nodes cause false invalidations.** Larger nodes, as in B-trees, do solve the capacity problem: more keys per node means fewer nodes and fewer version numbers. With a fan-out of 128, SC-BTree’s version numbers fit in the SCR easily. But now a single version number covers 128 keys. Suppose one host updates key 194. The version number of the whole node changes. Another host now reads key 298 from the same node; since the node’s version has changed, it must flush and re-read the node, even though key 298 has not changed. That is what we call a **false invalidation**. We made the metadata fit but introduced unnecessary cache flushes, and under 50% writes SC-BTree drops to 1.8 Mops/s.

### Problem 2: one version number for 128 keys

Prism §3.3, Figure 2

1 / 4 · One version number for the whole node

A large node holds 128 keys in the LNR and shares a single version number in the SCR. Host 2 has read key 298 before, so the whole node sits in its cache at version 7.

Host 1 changes one key; the node’s version number changes; host 2, which wants a different key from the same node, must flush and re-read all 128. One write, 127 unmodified keys flushed: a false invalidation.

An animation of two hosts and a 128-key B-tree node with one version number in the coherent region. Host 2 has the node cached at version 7; host 1 updates key 194 and the version becomes 8; host 2 reads key 298, sees the mismatch, and must flush and re-read the whole node.

**The core problem** is what we call the **updatable surface area**, defined as the portion of the index that can receive in-place modifications. In ART and B-trees, any node from root to leaf can be modified in place, so the updatable surface area spans the entire index, and every node needs a version number. That leaves a trade-off. Small nodes track changes precisely, but need too many version numbers. Large nodes make the metadata fit, but track changes too coarsely and cause false invalidations. Either way, we pay for excessive cache flushes, so just changing the node size does not solve the underlying problem.

**Summary.** So we come back to our question: what is a good index for partly coherent CXL? An index with a _small updatable surface area_. All in-place updates should be restricted to a small region that can fit in the SCR, and the bulk of the data must be immutable, so that it can live in the LNR. Perhaps surprisingly, a data structure built for disk is a much better fit than the in-memory indexes we just looked at.

### Small nodes overflow the SCR; large nodes cause false invalidations

Prism §3, Figures 1–2

small nodes large nodes

modeled: version numbers fit, false invalidations begin

every version number fits, but one write already invalidates 22 unmodified keys; smaller nodes avoid that and overflow the SCR again

The two ends are the paper’s measurements: SC-ART at ART’s smallest node size and SC-BTree at 128 keys per node. In between is a model that scales the paper’s 40M ART nodes inversely with node size, and the widget says so. There is no throughput axis, because the paper measures only the two ends.

An interactive slider over index node size. With small nodes, tens of millions of version numbers overflow the coherent region. With large nodes, one update falsely invalidates every other key in a 128-key node. The two ends are measured; the middle is a model.

<a id="prism"></a>

Paper two · SOSP 2026

## 6. Prism

A data structure built for disk is an unexpectedly good fit for partly coherent CXL.

That data structure is the **log-structured merge tree (LSM)**, the engine inside RocksDB, LevelDB, Bigtable, and Cassandra. A conventional LSM has a small in-memory structure called the **memtable**. All writes go there, and they are updated in place. The bulk of the data sits on disk in sorted, immutable files called **SSTables**, organized in levels, and a small **manifest** records which SSTables are in which level. When the memtable is full, it is flushed down as a new SSTable at level 0 (L0). In the background, _compaction_ merge-sorts SSTables into the next level and discards the old ones. L0 can hold overlapping keys, because each L0 SSTable comes from a separately flushed memtable, but from L1 onward each level is sorted, so only one SSTable per level can hold a given key. A read checks the memtable first, then every SSTable in L0, then at most one SSTable per level until it finds the key.

The key property of an LSM is that its updatable surface area is confined to the memtable. Our key insight is that this is exactly what partly coherent CXL asks for: LSMs confine in-place updates to a small region, while a large portion of the data structure is immutable. The memtable is small, typically a few megabytes, so it can be placed entirely in the SCR along with the manifest, where hardware maintains coherence with zero software overhead. SSTables are immutable for their whole lifetime, so while an SSTable is alive there is nothing to track, and they can live in the LNR. One thing remains to handle: memory reuse. When compaction discards an SSTable, its memory is recycled for a new one, so each SSTable gets a strictly increasing ID in the manifest, and a host that sees an ID for the first time flushes that SSTable’s region once before reading it. We call this port **SC-LSM**. So the key idea is to confine the updatable surface area to a region that fits in the SCR.

### What a good index for partly coherent CXL looks like

Prism §3.4, §4.1

The index as a triangle, its in-place-updatable part shaded, beside the SCR and the LNR. Switch the design: an ART or B+-tree can be modified anywhere, so the shading covers the whole index and its version numbers overflow the SCR; an LSM confines updates to the memtable at the top, which fits in the SCR, and keeps the bulk immutable in the LNR.

An interactive diagram of an index drawn as a triangle beside the coherent and non-coherent regions. For an ART or B+-tree the whole triangle is updatable and its version numbers overflow the coherent region. For an LSM only the apex, the memtable, is updatable and sits in the coherent region, with immutable SSTables below.

Even this straightforward port performs well. With 100M keys and a 128 MB SCR, SC-LSM beats SC-ART on all three YCSB workloads we tried, runs close to SC-BTree on the read-heavy ones, and beats it by up to 2.2× under 50% writes, because it has no false invalidations and no spilled version numbers. So limiting the updatable surface area helps. But this port inherits an old LSM problem: **compaction cannot keep up**. At high write rates the memtable fills and flushes quickly, producing L0 SSTables faster than compaction can drain them into the next level. Since L0 is not level-sorted, a point query may end up probing every L0 SSTable. We measured it: at 5% writes SC-LSM probes about 15 SSTables per read, and at 50% writes it jumps all the way up to 49. This is a well-known LSM challenge and not something our port introduced.

Being in memory gives us a way out that disk never had. In-place updates to the upper levels of an LSM are a non-starter on disk, because they need random I/O, which is exactly what LSMs exist to avoid. In memory, they are not that expensive. So the idea is to make the upper level of the LSM updatable in place: when a key is written again, we overwrite it instead of spawning a new SSTable. Fewer SSTables means less compaction pressure, a smaller L0, and fewer probes per read. But wait, doesn’t that bring back the updatable-surface-area problem? Yes it does, so we bound it. We call this layer the **bounded updatable layer (BUL)**. It sits above the SSTables and uses an ART as its index, with its data in the LNR and its version numbers in the SCR, and we limit its size so that all of its version numbers, even tracked per node, fit in the SCR. In the paper’s ablation at 5% writes, the BUL alone cuts the SSTables probed per read from 15 to 2.

### Prism’s architecture: where each tier lives

Prism §5, Figure 5

The memtable and the manifest sit in the SCR under hardware coherence. The BUL keeps its data in the LNR and its version numbers in the SCR. The SSTables below are immutable, in the LNR. The memtable and the BUL together form the updatable surface area, sized so that the SCR covers it.

Prism's architecture: a memtable and a manifest inside the coherent region, a bounded updatable layer with data in the non-coherent region and version numbers in the coherent region, and immutable SSTable levels below.

Putting everything together, we get **Prism**. The memtable (64 MB) and the manifest (2 MB) live in the SCR. The BUL’s index and data live in the LNR, and the remaining 62 MB of the SCR holds the BUL’s version numbers, one per node; that budget is what bounds the BUL’s size. Below the BUL sit the SSTables, all in the LNR. The memtable and the BUL together form the updatable surface area. Everything else is immutable.

The SCR is very limited, so Prism makes the memtable aware of it and changes the memtable from a write buffer into a **cache for frequently written keys**. A write first checks the memtable. On a hit, the key is updated in place. On a miss, the write goes to the BUL: if the key is absent there, it is added; if it is already present, this is a repeated write, so the key is promoted into the memtable and removed from the BUL. Periodically, and when the BUL is close to full, it flushes cold entries into new SSTables and removes them. So in Prism the most frequently written keys sit in the memtable under hardware coherence, less frequently written keys sit in the BUL with fine-grained software coherence, and the least frequently written keys end up in immutable SSTables. Keys written only once, the one-hit wonders, never take up SCR space.

A read checks the tiers in the same order: memtable, then BUL, then the SSTables, every one in L0 from newest to oldest and at most one per level from L1 on, stopping at the first hit.

### The three tiers and what each one holds

Prism §5

Prism’s three tiers and their coherence mechanisms

- Tier · Lives in · Holds · Coherence · Cost ·
- Memtable · SCR (64 MB) · The most frequently written keys · Hardware coherence · No software checks ·
- BUL · Data in LNR; version numbers in SCR (62 MB) · Less frequently written keys · Per-node version check · Fine-grained, bounded ·
- SSTables · LNR (the terabytes) · The least frequently written keys, immutable · Immutable + rising IDs; one flush on first sight · Coarse but safe ·

A 2 MB manifest in the SCR lists the live SSTables: 64 + 62 + 2 = 128 MB.

A table of Prism's three tiers. The memtable in the SCR holds the most frequently written keys under hardware coherence. The BUL holds less frequently written keys, with data in the LNR and version numbers in the SCR, checked per node. The SSTables in the LNR hold the least frequently written keys, immutable, with rising IDs and one flush on first sight.

We evaluate Prism by emulating shared CXL memory on a four-socket Intel Xeon server: one socket acts as the CXL device, with its uncore frequency throttled to mimic CXL latency, and the other three act as hosts. We cap the SCR at 128 MB and load 100M key-value pairs with 24-byte keys and 100-byte values, accessed with a Zipfian distribution. The paper has many more experiments (read-only and range workloads, ablations, SCR size sensitivity, real-world traces, comparisons with an RDMA index and with existing CXL systems). We cover two here.

**Mixed read-write.** At 50% writes, Prism reaches up to 6.2× SC-BTree’s peak throughput and 5.6× SC-ART’s. SC-BTree suffers from false invalidations, while SC-ART suffers from version number overflow. In Prism, repeated writes to hot keys are absorbed in the memtable with hardware coherence, and the rest land in the BUL, where they are tracked at fine granularity. Sweeping the write ratio tells the same story: SC-BTree drops off a cliff as the write ratio increases, but Prism declines much more gently.

### Throughput against write ratio

Prism Figure 7(c)

- SC-ART
- SC-BTree
- Prism

Values read off the paper’s Figure 7(c), one point per write ratio; the 6.2× and 5.6× in the text are peaks from Figure 7(b). SC-BTree falls from **9.3** to **1.8 Mops/s** between 10% and 50% writes, because every write falsely invalidates a whole node on every host that cached it. SC-ART stays between 3.0 and 2.5, because its version numbers overflow the SCR. Prism goes from 17.4 to 11.6 and leads at every write ratio.

Show the numbers

Throughput against write ratio

- Write ratio · SC-ART · SC-BTree · Prism ·
- 10% · 3.0 Mops/s · 9.3 Mops/s · 17.4 Mops/s ·
- 20% · 2.9 Mops/s · 4.2 Mops/s · 16.7 Mops/s ·
- 30% · 2.8 Mops/s · 2.6 Mops/s · 14.9 Mops/s ·
- 40% · 2.7 Mops/s · 2.2 Mops/s · 13.4 Mops/s ·
- 50% · 2.5 Mops/s · 1.8 Mops/s · 11.6 Mops/s ·

Three lines of throughput against write ratio from 10 to 50 percent. SC-BTree falls from 9.3 to 1.8 million operations per second, SC-ART stays near 3, and Prism declines from 17.4 to 11.6 while staying ahead throughout.

**A full KV store under YCSB.** Finally, we built a key-value store on top of each index and ran the YCSB suite on it. The takeaway: the heavier the write pressure, the larger Prism’s advantage, up to 7.4× over SC-BTree on YCSB-A and 9.4× on YCSB-F. Even on the read-only YCSB-C, traditionally an LSM’s weakness, Prism still comes out ahead of both.

### A full key-value store under YCSB

Prism Figure 9

- SC-ART
- SC-BTree
- Prism

Values read off the paper’s Figure 9. Prism’s lead is widest under writes, **7.4×** over SC-BTree on A and **9.4×** on F, because every write falsely invalidates a whole SC-BTree node, while SC-ART is held down everywhere by version number overflow. On the read-only C, Prism is still 1.1× ahead. On E, short range scans at 5% writes, SC-BTree wins. D reads the latest inserted keys; F is 50% read-modify-write (RMW).

Show the numbers

A full key-value store under YCSB

- Workload · SC-ART · SC-BTree · Prism ·
- YCSB-A · 50% writes · 2.2 Mops/s · 1.6 Mops/s · 11.8 Mops/s ·
- YCSB-B · 5% writes · 3.1 Mops/s · 13.0 Mops/s · 18.5 Mops/s ·
- YCSB-C · read-only · 3.3 Mops/s · 19.5 Mops/s · 21.0 Mops/s ·
- YCSB-D · read latest · 2.8 Mops/s · 12.8 Mops/s · 17.7 Mops/s ·
- YCSB-E · short scans · 2.9 Mops/s · 13.7 Mops/s · 9.8 Mops/s ·
- YCSB-F · 50% RMW · 1.9 Mops/s · 1.5 Mops/s · 14.1 Mops/s ·

Grouped bars across YCSB workloads A to F. Prism reaches 11.8, 18.5, 21.0, 17.7, 9.8 and 14.1 million operations per second; SC-BTree collapses to 1.6 and 1.5 on the two write-heavy workloads and wins only on E; SC-ART stays below 3.5 throughout.

Prism’s results

Overall, Prism reaches up to 9.4× the throughput of the ported in-memory indexes and 8.6–15.1× that of Tigon-SWcc, a Tigon-style index whose 100M-key index does not fit in the SCR, so it keeps migrating data in and out of CXL. It also beats Chime-CXL, an RDMA index ported to CXL that pays at least two cache flushes per leaf access, by 3.6–5.7×, and with 128 MB of SCR it matches the throughput SC-ART needs unlimited SCR to reach on YCSB-A. It is not a win everywhere. At 5% writes SC-BTree is faster on range scans, since sorted keys in one large node make a scan cheap; Prism takes the lead from 10% writes. And on read-only workloads Megalon’s index, which sits in each host’s local DRAM, is faster than Prism’s, which sits in CXL; Prism wins once there are writes, by 5.5× on YCSB-A. [Read the paper](https://dassl-uiuc.github.io/pdfs/papers/prism.pdf) for the rest.

### Range scans: where SC-BTree wins, and where it stops

Prism Figure 8

Both throughputs read off the paper’s Figure 8. At 5% writes SC-BTree wins range scans, because sorted neighbors in one node make a scan cheap. The lead flips to Prism at **10% writes** and reaches **6.0×** at 50%.

Show the numbers

Range scans: where SC-BTree wins, and where it stops

- Write ratio · SC-BTree · Prism · Prism ÷ SC-BTree · Winner ·
- 5% · 13.8 Mops/s · 9.8 Mops/s · 0.7× · SC-BTree ·
- 10% · 9.0 Mops/s · 10.1 Mops/s · 1.1× · Prism ·
- 20% · 4.0 Mops/s · 10.9 Mops/s · 2.7× · Prism ·
- 30% · 2.7 Mops/s · 10.5 Mops/s · 3.9× · Prism ·
- 40% · 2.0 Mops/s · 10.2 Mops/s · 5.1× · Prism ·
- 50% · 1.6 Mops/s · 9.5 Mops/s · 6.0× · Prism ·

A line of Prism's range-scan throughput relative to SC-BTree as write ratio grows: about 0.7 times at five percent writes, crossing 1.0 at ten percent, reaching six times at fifty percent.

<a id="sources"></a>

## Sources & further reading

Everything this post leans on: our papers first, then every external reference.

### Sources of truth

Megalon: Efficient Data Sharing for Partly Coherent CXL Memory. OSDI 2026 (best-paper nominee).

Jiyu Hu, Seokjoo Cho, Landon Johnson, Kiran Hombal, Shreesha G. Bhat, Marcos K. Aguilera, Ramnatthan Alagappan, Aishwarya Ganesan

[paper (PDF)](https://kstark007.github.io/assets/papers/Megalon/paper.pdf) · [slides (PDF)](https://kstark007.github.io/assets/papers/Megalon/slides.pdf) · [USENIX page](https://www.usenix.org/conference/osdi26/presentation/hu-jiyu) · [artifact on GitHub](https://github.com/dassl-uiuc/MEGALON-artifact)

Disk-Based LSMs: An Unexpectedly Good Index for Partly Coherent CXL Memory. SOSP 2026.

Kiran Hombal, Jiyu Hu, Marcos K. Aguilera, Ramnatthan Alagappan, Aishwarya Ganesan

[paper (PDF)](https://kstark007.github.io/assets/papers/Prism/paper.pdf) · [ACM DOI](https://doi.org/10.1145/3830418.3843886)

Intro to CXL: Data Sharing on Partly Coherent CXL Memory. Talk at ByteDance, 2026.

Kiran Hombal and Jiyu Hu. The deck is not public; slide numbers on this page refer to it.

The numbers in this post come from those three sources. Where a chart’s values were read off a paper figure rather than taken from a table, its caption says so. The background facts below were checked against each linked page; the one whose URL no longer resolves says so in its entry.

### CXL and hardware

- [CXL Consortium: About CXL, and the 2.0/3.0/3.2 specification releases](https://computeexpresslink.org/about-cxl/)
- [Sharma, Blankenship, Berger. An Introduction to the Compute Express Link (CXL) Interconnect. ACM Computing Surveys, 2024](https://arxiv.org/abs/2306.11227)
- [Sun et al. Demystifying CXL Memory with Genuine CXL-Ready Systems and Devices. MICRO 2023](https://arxiv.org/abs/2303.15375)
- [Liu et al. Systematic CXL Memory Characterization and Performance Analysis at Scale (Melody). ASPLOS 2025](https://people.cs.vt.edu/~jinshu/docs/papers/Melody_ASPLOS.pdf)
- [Just How Bad Is CXL Memory Latency? The Next Platform, 2022](https://www.nextplatform.com/2022/12/05/just-how-bad-is-cxl-memory-latency/)
- [Jain et al. (AMD). Memory Sharing with CXL: Hardware and Software Design Approaches. arXiv, 2024](https://arxiv.org/abs/2404.03245)
- Micron's Perspective on Impact of CXL on DRAM Bit Growth Rate. Whitepaper, 2023 (the chart behind the memory-wall figure, as reproduced in our talk; Micron's original URL no longer resolves)
- [Micron CZ120 CXL memory expansion modules: launch announcement, 2023](https://www.globenewswire.com/news-release/2023/08/07/2719764/14450/en/Micron-Launches-Memory-Expansion-Module-Portfolio-to-Accelerate-CXL-2-0-Adoption.html)
- [Samsung CMM-D (CXL Memory Module, DRAM): product page](https://semiconductor.samsung.com/cxl-memory/cmm-d/)
- [CXL Memory Disaggregation and Tiering: Lessons Learned from Storage. SNIA SDC 2023](https://www.snia.org/educational-library/cxl-memory-disaggregation-and-tiering-lessons-learned-storage-2023)

### Tiering and sharing systems

- [Agarwal & Wenisch. Thermostat: Application-transparent Page Management for Two-tiered Main Memory. ASPLOS 2017](https://dl.acm.org/doi/10.1145/3093337.3037706)
- [Raybuck et al. HeMem: Scalable Tiered Memory Management for Big Data Applications and Real NVM. SOSP 2021](https://dl.acm.org/doi/10.1145/3477132.3483550)
- [Weiner et al. TMO: Transparent Memory Offloading in Datacenters. ASPLOS 2022](https://dl.acm.org/doi/10.1145/3503222.3507731)
- [Li et al. Pond: CXL-Based Memory Pooling Systems for Cloud Platforms. ASPLOS 2023](https://dl.acm.org/doi/10.1145/3575693.3578835)
- [Maruf et al. TPP: Transparent Page Placement for CXL-Enabled Tiered-Memory. ASPLOS 2023](https://dl.acm.org/doi/10.1145/3582016.3582063)
- [Huang et al. Tigon: A Distributed Database for a CXL Pod. OSDI 2025](https://www.usenix.org/conference/osdi25/presentation/huang-yibo)

### Data structures and protocols

- [Papamarcos & Patel. A low-overhead coherence solution for multiprocessors with private cache memories (MESI's origin). ISCA 1984](https://dl.acm.org/doi/10.1145/800015.808204)
- [Calciu et al. Black-box Concurrent Data Structures for NUMA Architectures (Node Replication). ASPLOS 2017](https://dl.acm.org/doi/10.1145/3037697.3037721)
- [Leis, Kemper, Neumann. The Adaptive Radix Tree: ARTful Indexing for Main-Memory Databases. ICDE 2013](https://db.in.tum.de/~leis/papers/ART.pdf)
- [Leis et al. The ART of Practical Synchronization (Optimistic Lock Coupling). DaMoN 2016](https://dl.acm.org/doi/10.1145/2933349.2933352)
- [O'Neil et al. The Log-Structured Merge-Tree (LSM-Tree). Acta Informatica, 1996](https://dl.acm.org/doi/10.1007/s002360050048)
- [RocksDB (Meta) and LevelDB (Google): LSMs in production](https://github.com/facebook/rocksdb)

### Benchmarks

- [Cooper et al. Benchmarking Cloud Serving Systems with YCSB. SoCC 2010](https://dl.acm.org/doi/10.1145/1807128.1807152)

<a id="about"></a>

## About

Written by [Kiran Hombal](https://kstark007.github.io/) and [Jiyu Hu](https://jiyuuuhuuu.github.io/), PhD students at the [DASSL Lab, UIUC](https://dassl-uiuc.github.io/), advised by Ramnatthan Alagappan and Aishwarya Ganesan. The research described here was done jointly with our co-authors, including Marcos K. Aguilera at NVIDIA.

The systems and results are our papers’; the simplifications for a general audience are ours, and so are any errors they introduce. Every figure on this page is redrawn from the papers or the talk, and each plate names its source.

### Cite this post

Kiran Hombal and Jiyu Hu. "The Partly Coherent CXL: A field guide to shared CXL memory." kstark007.github.io, August 2026.

@misc{hombal2026onememory,
 title = {The Partly Coherent CXL: A field guide to shared CXL memory},
 author = {Kiran Hombal and Jiyu Hu},
 year = {2026},
 url = {https://kstark007.github.io/blog/one-memory-many-machines/},
 note = {Based on Megalon (OSDI '26) and Prism (SOSP '26)}
}

---

## Appendix: the numbers behind the figures

Every figure on the page, as data. Rendered from the same constants the page itself uses, so these values and the published charts cannot disagree.

### Headline stats

| label | value | detail |
| --- | --- | --- |
| Papers | 2 | OSDI '26 · SOSP '26 |
| Best-paper nominee | 1 | Megalon at OSDI '26 |

### Pin efficiency, DDR vs CXL

| Name | Value |
| --- | --- |
| ddrChannel | DDR5-6400 |
| ddrPins | ~200 signal pins |
| ddrBandwidth | ~51 GB/s |
| cxlLink | x16 PCIe 5.0 |
| cxlPins | 64 signal pins |
| cxlBandwidth | ~63 GB/s per direction |
| cxlRate | 32 GT/s, 128b/130b encoding |
| cxlGen6Bandwidth | ~126 GB/s per direction at PCIe 6.0 rates |
| perPinAdvantage | 4× |

### Latency ladder

| tier | ns | label | note | basis | accent |
| --- | --- | --- | --- | --- | --- |
| L1 cache | 1 | ~1 ns | on the core itself | textbook order of magnitude | false |
| L2 cache | 4 | ~4 ns | private per core | textbook order of magnitude | false |
| L3 cache | 15 | ~15 ns | shared on the die | textbook order of magnitude | false |
| Local DRAM | 114 | ~111–117 ns | over the DDR bus | measured on three Melody platforms | false |
| CXL memory | 300 | ~170–400 ns | about one NUMA hop away | Melody measured 214–394 ns; industry quotes 170–250 ns | true |
| RDMA read | 3000 | ~2–10 µs | network round trip | commonly reported range | false |
| NVMe SSD | 30000 | ~10–100 µs | flash storage | commonly reported range | false |

### CXL generations

| version | year | headline | what |
| --- | --- | --- | --- |
| CXL 1.0 / 1.1 | 2019 | Expansion | One host attaches more memory over PCIe and uses plain loads and stores. |
| CXL 2.0 | 2020 | Pooling | Switching lets a rack carve one memory pool into slices, but each slice still belongs to one host at a time. |
| CXL 3.x | 2022–24 | Sharing | Fabrics and true multi-host sharing: several machines map the same region, at the same time. |

### The MESI walkthrough

| caption | detail | cpu1 | cpu2 | cpu3 | memory | bus |
| --- | --- | --- | --- | --- | --- | --- |
| Three CPUs, one memory | Memory holds A = 1. No CPU has it cached yet. | – | – | – | A = 1 |  |
| CPU 1 reads A | Cache miss. The value comes from memory; CPU 1 holds the only copy, so its line is marked Exclusive. | E 1 | – | – | A = 1 | Read(A) → memory |
| CPU 2 reads A | CPU 1 sees the read on the bus and shares its copy. Both lines drop to Shared. | S 1 | S 1 | – | A = 1 | Read(A) · served by CPU 1 |
| CPU 3 reads A | Same again. Three caches, three copies, all Shared, and all still telling the truth. | S 1 | S 1 | S 1 | A = 1 | Read(A) |
| CPU 2 wants to write | Before it may touch A, it broadcasts Invalidate. Every other copy must die first. | S 1 | S 1 | S 1 | A = 1 | Invalidate(A) → |
| CPUs 1 and 3 invalidate | They mark their lines Invalid and acknowledge. Stale copies are now impossible. | I – | S 1 | I – | A = 1 | ← ACK · ACK |
| CPU 2 writes A = 2 | Its line becomes Modified: the one true copy, newer than memory itself. | I – | M 2 | I – | A = 1 (stale) |  |
| CPU 3 reads A again | A miss, because its line is Invalid. The read goes to the bus, and CPU 2 must answer it, not memory. | I – | M 2 | I – | A = 1 (stale) | Read(A) · CPU 2 owns it |
| CPU 2 writes back | It pushes A = 2 to memory and supplies CPU 3. Both settle at Shared. | I – | S 2 | S 2 | A = 2 | WriteBack(A = 2) |
| Coherent again | Every reader sees 2. This dance runs beneath every write your programs make, in hardware, for free. Within one machine. | I – | S 2 | S 2 | A = 2 |  |

### The stale read, step by step

| caption | detail |
| --- | --- |
| Host 1 reads A from the LNR | The value drops into host 1’s CPU cache, as every read does. |
| Host 2 writes A′ | The LNR now holds A′. No invalidation is sent to anyone, because the LNR has no coherence machinery to send one. |
| Host 1 reads A again | Its cache answers: “I have that.” It serves the old A. Nothing in the hardware detects the lie. |
| The stale read | Host 1 is now computing on stale data. This is the bug class the rest of the post is about. |

### Software coherence, step by step

| caption | detail |
| --- | --- |
| Host 1 reads A | Host 1 reads A from the LNR and notes its version from A’s coherence record in the SCR: 0. |
| Host 2 writes A′ | Host 2 writes A′, flushes it to the LNR, and bumps A’s version in the SCR to 1. The LNR still sends no invalidation, but the SCR is hardware-coherent, so every host sees the new version. |
| Host 1 checks the SCR | Before trusting its cache, host 1 checks A’s record. Its copy is version 0 and the SCR says 1. Mismatch, so host 1 invalidates its cached A. |
| Host 1 reads fresh data | The read misses the cache and fetches A′ from the LNR; host 1’s copy now matches version 1 in the SCR. Correct, at the price of one metadata record per shared object in the scarce SCR. |

### The partly coherent model

| Name | Value |
| --- | --- |
| scrLabel | a few hundred MB |
| lnrLabel | several TB |
| scrMB | 300 |
| lnrMB | 4194304 |
| vendors | AMD, Micron, and Samsung |
| why | snoop filters and back-invalidation do not scale with memory size |

### HCMeta's arithmetic

| Name | Value |
| --- | --- |
| exampleKeyBytes | 40 |
| bytesPerObject | 52 |
| objectsAt100MB | 1.9M |
| megalonBytesPerObject | 4 |
| megalonObjectsAt100MB | ~25M |
| tigonDropDatasets | 2.4M to 24M objects |
| tigonDropFactor | 10× |
| tigonCrossHost | 20% cross-host transactions |
| churnRoundTrip | 55 µs |
| megalonChurnCheaper | 8× |

### HCMeta collapse (Megalon Fig. 1c, Mops/s)

| datasetM | hcmeta | unlimited |
| --- | --- | --- |
| 1.2 | 15.5 | 15.5 |
| 2.4 | 15.2 | 15.3 |
| 4.8 | 1 | 15.1 |
| 7.2 | 0.9 | 15 |
| 12 | 0.7 | 14.6 |
| 18 | 0.6 | 13.8 |

### Megalon results

| Name | Value |
| --- | --- |
| readOnlyLargeDatasets | 15× |
| readWriteOverflow | 10× |
| readWriteFiftyPercent | 4× |
| smallScr | 8.4× |
| smallScrSize | 32 MB |
| ycsbRange | 3–14× |
| largerDatasetsNoChurn | 12× |
| churnImprovement | 2.5–14.9× |
| churnCheaper | 8× |
| pageCacheRange | 1.9–5.7× |
| dramPremium | in the read-only run with 24M objects, Megalon used 27.71 GB of memory in total against HCMeta's 25.76 GB, 7.6% more, for 24.4 against 1.6 Mops/s |

### Megalon vs HCMeta (Mops/s, 5% writes, 200 MB SCR)

| objects | hcmeta | megalon |
| --- | --- | --- |
| 4.8M | 16.6 | 17.7 |
| 7.2M | 5.7 | 17.2 |
| 12M | 2.5 | 17.4 |
| 24M | 1.7 | 17.4 |

### The SC-ART / SC-BTree dilemma

| Name | Value |
| --- | --- |
| keys | 100M |
| artNodes | ~40M |
| realisticScr | 128 MB |
| artCoverageAt100M | about 40% |
| versionBytes | 8 |
| versionsFitAt128MB | 16M |
| scArtSlowdown | 20× |
| scArtSlowdownBasis | with no SCR at all, against a 128 MB SCR |
| scBtreeFanout | 128 |
| scBtreeMops | 1.8 |
| scArtUnlimitedMops | 12 |

### Problem 1, step by step

| caption | detail |
| --- | --- |
| A small tree: every version number fits | Each node of SC-ART keeps its version number in the SCR. With five nodes, five of the eight slots are used, and a host checks a node’s version there before trusting its cached copy. |
| The tree grows | Eight leaves arrive and each needs a slot too. Thirteen version numbers do not fit in eight slots, so five of them spill into the LNR. |
| A spilled version number can itself be stale | The LNR has no cross-host coherence, so a host cannot tell whether its cached copy of a spilled version number is fresh. It has to flush and re-read it on every access, even if nothing has changed. |
| The cost at scale | With 100M keys ART has ~40M inner nodes, and a 128 MB SCR holds about 40% of their version numbers. Take the SCR away entirely, so that every version number spills, and SC-ART runs about 20× slower than with a 128 MB SCR. |

### Problem 2, step by step

| caption | detail |
| --- | --- |
| One version number for the whole node | A large node holds 128 keys in the LNR and shares a single version number in the SCR. Host 2 has read key 298 before, so the whole node sits in its cache at version 7. |
| Host 1 updates key 194 | Host 1 writes key 194 in place, flushes it to the LNR, and bumps the node’s version number in the SCR from 7 to 8. |
| Host 2 reads key 298 | Host 2 checks the node’s version first: its cache says 7, the SCR says 8. It must flush and re-read the whole node, even though key 298 has not changed. |
| A false invalidation | One write to one key forced 127 unmodified keys out of host 2’s cache. The metadata fits, but every write now costs a flush on every host that cached the node. |

### Updatable surface area, by index

| key | label | mutableTo | verdict | caption |
| --- | --- | --- | --- | --- |
| tree | ART or B+-tree | 1 | the whole index | Any node from root to leaf can be modified in place, so the updatable surface area spans the entire index. Every node needs a version number, and together they do not fit in the SCR. |
| lsm | LSM | 0.28 | the memtable | In-place updates are confined to the memtable, which fits in the SCR. The SSTables below are immutable for their whole lifetime, so they can live in the LNR with no coherence tracking. |

### Prism's three tiers

| tier | livesIn | holds | mechanism | cost |
| --- | --- | --- | --- | --- |
| Memtable | SCR (64 MB) | The most frequently written keys | Hardware coherence | No software checks |
| BUL | Data in LNR; version numbers in SCR (62 MB) | Less frequently written keys | Per-node version check | Fine-grained, bounded |
| SSTables | LNR (the terabytes) | The least frequently written keys, immutable | Immutable + rising IDs; one flush on first sight | Coarse but safe |

### Prism results

| Name | Value |
| --- | --- |
| readOnlyOverScArt | 6.3× |
| readOnlyOverScBtree | 1.1× |
| mixedOverScBtree | 6.2× |
| mixedOverScArt | 5.6× |
| ycsbAOverScBtree | 7.4× |
| writeHeavyOverScBtree | 9.4× |
| overRdmaIndex | 3.6–5.7× |
| overCxlSystems | 8.6–15.1× |
| overMegalonWriteHeavy | 5.5× |
| overMegalonReadMostly | 1.6× |
| twitterAvgOverScBtree | 3.9× |
| scLsmOverScBtree | 2.2× |
| probesAt5 | 15 |
| probesAt50 | 49 |
| probesWithBul | 2 |
| rangeFlipWriteRatio | 10% |
| rangeAt50 | 6.0× |
| unlimitedScrReadHeavy | 83–88% |
| matchesUnlimited | with 128 MB of SCR, Prism matches the throughput SC-ART needs unlimited SCR to reach on the write-heavy workload |
| testbed | 4-socket Intel Xeon Gold 6418H; one NUMA node as an emulated CXL device with uncore-throttled latency; 128 MB SCR; 100M pairs (24 B keys, 100 B values), Zipfian 0.99 |

### Prism under YCSB (Mops/s)

| workload | scArt | scBtree | prism |
| --- | --- | --- | --- |
| YCSB-A · 50% writes | 2.2 | 1.6 | 11.8 |
| YCSB-B · 5% writes | 3.1 | 13 | 18.5 |
| YCSB-C · read-only | 3.3 | 19.5 | 21 |
| YCSB-D · read latest | 2.8 | 12.8 | 17.7 |
| YCSB-E · short scans | 2.9 | 13.7 | 9.8 |
| YCSB-F · 50% RMW | 1.9 | 1.5 | 14.1 |

### Range-scan crossover (Prism ÷ SC-BTree)

| writeRatio | scBtree | prism |
| --- | --- | --- |
| 5 | 13.8 | 9.8 |
| 10 | 9 | 10.1 |
| 20 | 4 | 10.9 |
| 30 | 2.7 | 10.5 |
| 40 | 2 | 10.2 |
| 50 | 1.58 | 9.5 |

### Throughput against write ratio (Prism Fig. 7c, Mops/s)

| writeRatio | scArt | scBtree | prism |
| --- | --- | --- | --- |
| 10 | 3 | 9.3 | 17.4 |
| 20 | 2.9 | 4.2 | 16.7 |
| 30 | 2.8 | 2.6 | 14.9 |
| 40 | 2.7 | 2.2 | 13.4 |
| 50 | 2.5 | 1.8 | 11.6 |

## Citing this post

```bibtex
@misc{hombal2026onememory,
  title  = {The Partly Coherent CXL: A field guide to shared CXL memory},
  author = {Kiran Hombal and Jiyu Hu},
  year   = {2026},
  url    = {https://kstark007.github.io/blog/one-memory-many-machines/},
  note   = {Based on Megalon (OSDI '26) and Prism (SOSP '26)}
}
```
