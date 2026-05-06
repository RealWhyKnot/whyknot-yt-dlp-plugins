## Install

Wheel:

```
pip install "whyknot-yt-dlp-plugins @ https://github.com/{full-repo}/releases/download/{tag}/{wheel-name}"
```

Sdist:

```
pip install "https://github.com/{full-repo}/releases/download/{tag}/{sdist-name}"
```

The package only needs to co-reside in the same Python environment as `yt-dlp`. The plugin loader walks any installed package for the `yt_dlp_plugins.extractor` namespace; no registration call is required.
