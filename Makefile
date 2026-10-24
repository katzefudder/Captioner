# ExifTool is bundled into the app (ADR 0001, item 1). Version and checksum are
# fixed so a build is reproducible. New version: from exiftool.org/ver.txt,
# checksum from exiftool.org/checksums.txt.
EXIFTOOL_VERSION ?= 13.59
EXIFTOOL_SHA256 ?= 668ea3acececb7235fbd0f4900e72d5f12c9b07e5c778fd36cb1e9b5828fd65a
EXIFTOOL_URL = https://sourceforge.net/projects/exiftool/files/Image-ExifTool-$(EXIFTOOL_VERSION).tar.gz/download
EXIFTOOL_DIR = vendor/exiftool

POETRY = env -u VIRTUAL_ENV poetry

.PHONY: install run test icons translations manual manual-screenshots bundle verify dmg pkg installer notarize clean

install:
	$(POETRY) install

run:
	$(POETRY) run python -m captioner "$(FOLDER)"

test:
	$(POETRY) run python -m pytest

# Regenerate all icons from captioner/resources/logo.svg (the result is checked in)
icons:
	$(POETRY) run python scripts/make_icons.py

# Manuals: docs/manual/anleitung.html (German) and manual.html (English), shared anleitung.css
# -> docs/Captioner-Anleitung.pdf and docs/Captioner-Manual.pdf (checked in). Needs WeasyPrint
# (brew install weasyprint). manual-screenshots creates img/ and img/en/ (needs ExifTool).
manual:
	cd docs/manual && weasyprint anleitung.html ../Captioner-Anleitung.pdf
	cd docs/manual && weasyprint manual.html ../Captioner-Manual.pdf

manual-screenshots:
	$(POETRY) run python scripts/manual_screenshots.py de
	$(POETRY) run python scripts/manual_screenshots.py en

# Translations: extract the texts, update the catalogues (.po), compile them (.mo).
# Translate the .po files by hand (or with Poedit); .po and .mo are checked in.
LOCALES = captioner/locale
translations:
	$(POETRY) run pybabel extract -F babel.cfg -k _ -k N_ -k ngettext:1,2 --no-location \
		--omit-header --sort-output -o $(LOCALES)/captioner.pot .
	$(POETRY) run pybabel update -i $(LOCALES)/captioner.pot -d $(LOCALES) -D captioner \
		--no-fuzzy-matching --ignore-obsolete
	$(POETRY) run pybabel compile -d $(LOCALES) -D captioner --statistics

$(EXIFTOOL_DIR)/exiftool:
	rm -rf vendor && mkdir -p vendor
	curl -fsSL -o vendor/exiftool.tar.gz "$(EXIFTOOL_URL)"
	echo "$(EXIFTOOL_SHA256)  vendor/exiftool.tar.gz" | shasum -a 256 -c -
	tar -xzf vendor/exiftool.tar.gz -C vendor
	mkdir -p $(EXIFTOOL_DIR)
	cp vendor/Image-ExifTool-$(EXIFTOOL_VERSION)/exiftool $(EXIFTOOL_DIR)/
	cp -R vendor/Image-ExifTool-$(EXIFTOOL_VERSION)/lib $(EXIFTOOL_DIR)/
	rm -rf vendor/exiftool.tar.gz vendor/Image-ExifTool-$(EXIFTOOL_VERSION)

# macOS app (arm64) in dist/Captioner.app, settings in Captioner.spec.
# Signed with CODESIGN_IDENTITY="Developer ID Application: …" (hardened runtime),
# otherwise ad-hoc.
bundle: $(EXIFTOOL_DIR)/exiftool
	$(POETRY) run pyinstaller --noconfirm Captioner.spec
	$(POETRY) run python scripts/package_macos.py verify

verify:
	$(POETRY) run python scripts/package_macos.py verify

# Installers, see readme.md "Installer". INSTALLER_IDENTITY signs the PKG.
dmg: bundle
	$(POETRY) run python scripts/package_macos.py dmg

pkg: bundle
	$(POETRY) run python scripts/package_macos.py pkg

installer: bundle
	$(POETRY) run python scripts/package_macos.py dmg
	$(POETRY) run python scripts/package_macos.py pkg

# Needs a Developer ID signature and NOTARY_PROFILE (xcrun notarytool store-credentials)
notarize:
	$(POETRY) run python scripts/package_macos.py notarize

clean:
	rm -rf build dist vendor
