# ExifTool wird in die App gebuendelt (ADR 0001, Punkt 1). Version und Pruefsumme
# fest, damit ein Build reproduzierbar ist. Neue Version: von exiftool.org/ver.txt,
# Pruefsumme aus exiftool.org/checksums.txt.
EXIFTOOL_VERSION ?= 13.59
EXIFTOOL_SHA256 ?= 668ea3acececb7235fbd0f4900e72d5f12c9b07e5c778fd36cb1e9b5828fd65a
EXIFTOOL_URL = https://sourceforge.net/projects/exiftool/files/Image-ExifTool-$(EXIFTOOL_VERSION).tar.gz/download
EXIFTOOL_DIR = vendor/exiftool

POETRY = env -u VIRTUAL_ENV poetry

.PHONY: install run test icons bundle verify dmg pkg installer notarize clean

install:
	$(POETRY) install

run:
	$(POETRY) run python -m captioner "$(FOLDER)"

test:
	$(POETRY) run python -m pytest

# Alle Icons aus captioner/resources/logo.svg neu erzeugen (Ergebnis ist eingecheckt)
icons:
	$(POETRY) run python scripts/make_icons.py

$(EXIFTOOL_DIR)/exiftool:
	rm -rf vendor && mkdir -p vendor
	curl -fsSL -o vendor/exiftool.tar.gz "$(EXIFTOOL_URL)"
	echo "$(EXIFTOOL_SHA256)  vendor/exiftool.tar.gz" | shasum -a 256 -c -
	tar -xzf vendor/exiftool.tar.gz -C vendor
	mkdir -p $(EXIFTOOL_DIR)
	cp vendor/Image-ExifTool-$(EXIFTOOL_VERSION)/exiftool $(EXIFTOOL_DIR)/
	cp -R vendor/Image-ExifTool-$(EXIFTOOL_VERSION)/lib $(EXIFTOOL_DIR)/
	rm -rf vendor/exiftool.tar.gz vendor/Image-ExifTool-$(EXIFTOOL_VERSION)

# macOS-App (arm64) unter dist/Captioner.app, Einstellungen in Captioner.spec.
# Mit CODESIGN_IDENTITY="Developer ID Application: …" signiert (Hardened Runtime),
# sonst ad-hoc.
bundle: $(EXIFTOOL_DIR)/exiftool
	$(POETRY) run pyinstaller --noconfirm Captioner.spec
	$(POETRY) run python scripts/package_macos.py verify

verify:
	$(POETRY) run python scripts/package_macos.py verify

# Installer, siehe readme.md "Installer". INSTALLER_IDENTITY signiert das PKG.
dmg: bundle
	$(POETRY) run python scripts/package_macos.py dmg

pkg: bundle
	$(POETRY) run python scripts/package_macos.py pkg

installer: bundle
	$(POETRY) run python scripts/package_macos.py dmg
	$(POETRY) run python scripts/package_macos.py pkg

# Braucht Developer-ID-Signatur und NOTARY_PROFILE (xcrun notarytool store-credentials)
notarize:
	$(POETRY) run python scripts/package_macos.py notarize

clean:
	rm -rf build dist vendor
