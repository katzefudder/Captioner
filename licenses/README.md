# Third-party software in Captioner

Captioner itself is licensed under the GNU General Public License v3.0 or later
(see `LICENSE`). The app bundles the following software, each under its own license.

| Component | Used for | License | Text |
|---|---|---|---|
| Qt 6 / PySide6 / Shiboken6 (The Qt Company) | user interface | LGPL-3.0 (alternatively GPL-2.0/GPL-3.0) | `LGPL-3.0.txt`, `../LICENSE` |
| ExifTool (Phil Harvey) | reading and writing metadata | same terms as Perl: GPL-1.0-or-later or Artistic License | `../LICENSE` |
| Strawberry Perl (Windows only, inside ExifTool) | runs ExifTool | see `exiftool/exiftool_files/Licenses_Strawberry_Perl.zip` | in the bundle |
| Python 3.11 (Python Software Foundation) | runtime | PSF License | `Python.txt` |
| Pillow | image previews | MIT-CMU (incl. bundled libjpeg, libtiff, zlib …) | `Pillow.txt` |
| platformdirs | settings and cache folders | MIT | `platformdirs.txt` |
| tomli-w | writing settings and templates | MIT | `tomli-w.txt` |
| c2pa-python, c2pa-rs (Adobe, Content Authenticity Initiative) | reading Content Credentials | MIT OR Apache-2.0 (used under MIT) | `c2pa.txt` |
| PyInstaller bootloader | starting the bundled app | GPL-2.0-or-later with bootloader exception | `PyInstaller.txt` |

Map tiles and place search come from OpenStreetMap at runtime
(© OpenStreetMap contributors, ODbL); nothing of it is bundled.

Qt and PySide6 are used as shared libraries; they can be replaced in the installed app
(`Captioner.app/Contents/Frameworks` on macOS, `_internal` on Windows). The source code of
Qt is available at https://download.qt.io/, that of PySide6 at https://code.qt.io/.
