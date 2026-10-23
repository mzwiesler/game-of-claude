# Third-party notices

Game of Claude is licensed under the MIT License (see `LICENSE`). This file lists everything it
uses that is not its own, and under which terms. Last checked: 2026-10-23.

## Bundled code and assets

None. The repository contains no third-party source code, libraries, fonts, images or sounds:

- Python: standard library only, no packages to install.
- JavaScript / HTML / CSS: hand-written vanilla JS, no frameworks, no CDN scripts or stylesheets.
- Fonts: the system font stack (`system-ui`, `ui-monospace`, …), nothing is embedded or downloaded.
- Icons and arena art: inline SVG drawn in this repository; `claude-telemetry.ico` is rasterised
  from the favicon by `app.py` (`--write-icon`).
- Sounds: synthesised at runtime with the Web Audio API.

## Used at runtime, not distributed

These are used on the user's machine but are not part of this repository. Each is governed by its
own license, which the user accepts by installing or using it.

| Component | Used by | License / terms |
|---|---|---|
| Python 3 interpreter and standard library | everything | [PSF License Agreement](https://docs.python.org/3/license.html) |
| Claude Code (`claude` CLI) and its transcripts | `collect.py` reads its files; `insights.py --claude` runs `claude -p` | [Anthropic Commercial Terms](https://www.anthropic.com/legal/commercial-terms) or [Consumer Terms](https://www.anthropic.com/legal/consumer-terms), whichever covers your account |
| Microsoft Edge / Google Chrome / Chromium | `app.py` opens the dashboard window | the respective browser's license terms |
| Windows Task Scheduler, PowerShell, `wsl.exe` | `insights.py --install-schedule`, `app.py --install-shortcut` | part of Windows, Microsoft Software License Terms |
| [PokeAPI sprites](https://github.com/PokeAPI/sprites) | `poke.js` loads Pokémon sprite images from `raw.githubusercontent.com` (Pokémon theme only) | repository under [CC0 1.0](https://github.com/PokeAPI/sprites/blob/master/LICENCE.txt); per its licence file, *"All image contents within are Copyright The Pokémon Company."* The images are never copied into this repository, an export or a release. |

## Trademarks

- **Pokémon** and the Pokémon names are trademarks of Nintendo, Creatures Inc. and GAME FREAK inc.
  The Pokémon theme is an unofficial fan feature, not affiliated with, endorsed or sponsored by
  Nintendo, Game Freak, Creatures or The Pokémon Company. Only names and game-mechanic facts are
  used; the sprite images remain with their owners (see above).
- **Dungeons & Dragons** and **D&D** are trademarks of Wizards of the Coast LLC. The D&D theme is
  an unofficial homage, not affiliated with or endorsed by Wizards of the Coast. Its monster names
  and the d20 mechanics are generic or appear in the System Reference Document 5.1
  ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)); no SRD text is reproduced.
- **Claude** and **Claude Code** are trademarks of Anthropic, PBC. This project is not affiliated
  with or endorsed by Anthropic.
- Microsoft, Windows, Edge and Google Chrome are trademarks of their respective owners.

If you redistribute Game of Claude, keep `LICENSE` and this file with it. The MIT License covers
this project's own code only; it grants no rights in the third-party trademarks or images above.
