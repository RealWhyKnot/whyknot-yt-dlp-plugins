# yt-dlp's plugin loader walks this exact namespace path:
#   yt_dlp_plugins.extractor.*
# Any module placed here that defines a class subclassing
# `yt_dlp.extractor.common.InfoExtractor` is automatically picked up at
# yt-dlp startup. No registration call is required.
#
# Documentation: https://github.com/yt-dlp/yt-dlp/wiki/Plugin-Development
