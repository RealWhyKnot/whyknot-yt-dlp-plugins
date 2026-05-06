## Local development

Pip / venv:

```
git clone https://github.com/{full-repo}.git
cd whyknot-yt-dlp-plugins
python -m venv .venv
. .venv/Scripts/activate          # Windows; use `source .venv/bin/activate` on Linux/macOS
pip install --upgrade pip
pip install --pre "yt-dlp[default]"
pip install -e .
yt-dlp -v --simulate --skip-download \
  "https://plugin-test.whyknot.dev/test/sample"
```

Conda:

```
git clone https://github.com/{full-repo}.git
cd whyknot-yt-dlp-plugins
conda create -n yt-dlp-plugins python=3.11 -y
conda activate yt-dlp-plugins
pip install --pre "yt-dlp[default]"
pip install -e .
yt-dlp -v --simulate --skip-download \
  "https://plugin-test.whyknot.dev/test/sample"
```

The verbose output should print a line starting with `Extractor Plugins:` listing every plugin extractor yt-dlp loaded.
