# Ambi character icon

`ambi-source.png` is the approved blue variant of the existing Ambi mascot,
created with the image-generation tool on 1 November 2026 using the original
local Ambi character icon as the edit target. It preserves the character and
uses a transparent background; it does not contain OpenAI branding.

`uv run --locked python scripts/build-icons.py` exports the source into PNG,
macOS ICNS, Windows ICO, and the small web icon. These are format/size exports,
not additional artwork transformations. The Mac bundle loads `Ambi.icns` and
sets the runtime application icon; Windows embeds the matching ICO into its
executable and uses it for its taskbar/window icon.
