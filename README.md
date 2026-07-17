# Kiran Hombal's Personal Website

Personal academic website for [Kiran Hombal](https://kstark007.github.io/).

## Fonts

The site uses [Computer Modern Unicode](https://cm-unicode.sourceforge.io/) Sans Serif
(`cmunss` regular, `cmunsx` bold), shipped as WOFF2 subset to Latin-1 + General
Punctuation. To regenerate from the upstream TTFs:

```sh
pip install fonttools brotli
pyftsubset cmunss.ttf \
  --unicodes="U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+2074,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD" \
  --layout-features='*' --flavor=woff2 --output-file=assets/fonts/cmunss.woff2
```

## Acknowledgments

This website is built using the [minimal-research-theme](https://github.com/SebastinSanty/minimal-research-theme) by [Sebastin Santy](http://sebastinsanty.com/).

Special thanks to [Shreesha G. Bhat](https://shreesha00.github.io/) for sharing his website configuration and styling customizations.
