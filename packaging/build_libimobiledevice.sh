#!/bin/bash
# Build libimobiledevice 1.4.0 (library + ideviceinfo) for iPhone App Manager.
#
# Why this exists: the MSYS2 package is still libimobiledevice 1.3.0, whose idevice_connect() cannot read the
# address of a Wi-Fi (network) device on Windows (upstream fixed that in commit a172604, released in 1.4.0).
# The release therefore ships libimobiledevice-1.0.dll and ideviceinfo.exe built from the unmodified upstream
# 1.4.0 release tarball. Everything else in tools\libimobiledevice still comes from MSYS2.
#
# Run it in an MSYS2 UCRT64 shell (or:  C:\msys64\usr\bin\bash.exe -l packaging/build_libimobiledevice.sh ...):
#     packaging/build_libimobiledevice.sh <sources-dir> <work-dir> <output-dir>
#   <sources-dir>  folder holding the two upstream tarballs listed below (packaging/third-party-sources)
#   <work-dir>     scratch folder for the unpacked sources and the build (created if missing)
#   <output-dir>   receives libimobiledevice-1.0.dll, ideviceinfo.exe and BUILD-INFO.txt
#
# Build-time packages (MSYS2 UCRT64):  mingw-w64-ucrt-x86_64-gcc, -make (or msys make), -pkgconf, -curl
#   (curl is needed only because libtatsu's configure checks for libcurl) and the runtime libraries the
#   release already bundles: libplist, libimobiledevice-glue, libusbmuxd, openssl.
#
# libtatsu is a BUILD-TIME prerequisite only: libimobiledevice 1.4.0's configure insists on it, but the
# resulting DLL and ideviceinfo.exe do not import libtatsu.dll (or libcurl). This script checks that and fails
# if it ever changes. No MSYS2 patches are applied: of the 7 patches MSYS2 carries for 1.3.0, three only fix
# the Python/Cython bindings (not built here) and the other four are already part of 1.4.0 or concern code
# that moved to libimobiledevice-glue.
set -o pipefail

LIMD_TARBALL="libimobiledevice-1.4.0.tar.bz2"
LIMD_SHA256="23cc0077e221c7d991bd0eb02150a0d49199bcca1ddf059edccee9ffd914939d"
TATSU_TARBALL="libtatsu-1.0.5.tar.bz2"
TATSU_SHA256="536fa228b14f156258e801a7f4d25a3a9dd91bb936bf6344e23171403c57e440"

if [ $# -ne 3 ]; then
    echo "usage: $0 <sources-dir> <work-dir> <output-dir>" >&2
    exit 2
fi
export MSYSTEM=UCRT64
# shellcheck disable=SC1091
source /etc/profile
set -eu                                                # MSYS2's /etc/profile is not safe to source under -e or -u
SRC_DIR="$(cd "$1" && pwd)"
mkdir -p "$2" "$3"
WORK="$(cd "$2" && pwd)"
OUT="$(cd "$3" && pwd)"

check_sha256() {
    local file="$1" want="$2" got
    got="$(sha256sum "$file" | cut -d' ' -f1)"
    if [ "$got" != "$want" ]; then
        echo "SHA-256 mismatch for $file: got $got, expected $want" >&2
        exit 1
    fi
    echo "verified $(basename "$file")  $got"
}
check_sha256 "$SRC_DIR/$LIMD_TARBALL" "$LIMD_SHA256"
check_sha256 "$SRC_DIR/$TATSU_TARBALL" "$TATSU_SHA256"

PREFIX="$WORK/prefix"
mkdir -p "$WORK/src" "$WORK/build-tatsu" "$WORK/build-limd" "$PREFIX"
tar -xjf "$SRC_DIR/$TATSU_TARBALL" -C "$WORK/src"
tar -xjf "$SRC_DIR/$LIMD_TARBALL" -C "$WORK/src"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"
export SOURCE_DATE_EPOCH=1760000000                    # fixed, so embedded dates do not vary between builds
# Same output regardless of the work folder, and no link timestamp in the PE headers.
export CFLAGS="-O2 -ffile-prefix-map=$WORK=/build"
export LDFLAGS="-Wl,--no-insert-timestamp"

echo "=== libtatsu 1.0.5 (build-time prerequisite, not shipped)"
( cd "$WORK/build-tatsu" && "$WORK/src/libtatsu-1.0.5/configure" --prefix="$PREFIX" --disable-static >/dev/null \
    && make -j4 >/dev/null && make install >/dev/null )

echo "=== libimobiledevice 1.4.0"
( cd "$WORK/build-limd" && "$WORK/src/libimobiledevice-1.4.0/configure" --prefix="$PREFIX" \
    --without-cython --disable-static --enable-shared >/dev/null && make -j4 >/dev/null && make install-strip >/dev/null )

DLL="$PREFIX/bin/libimobiledevice-1.0.dll"
EXE="$PREFIX/bin/ideviceinfo.exe"
for f in "$DLL" "$EXE"; do
    [ -f "$f" ] || { echo "missing build output: $f" >&2; exit 1; }
    if objdump -p "$f" | grep -i -E "DLL Name: .*(tatsu|curl)" >/dev/null; then
        echo "$f imports libtatsu/libcurl - the dependency analysis in packaging/third_party.py no longer holds" >&2
        exit 1
    fi
done
cp "$DLL" "$EXE" "$OUT/"
{
    echo "libimobiledevice 1.4.0 build for iPhone App Manager"
    echo "libimobiledevice tarball : $LIMD_TARBALL  sha256 $LIMD_SHA256"
    echo "libtatsu tarball         : $TATSU_TARBALL  sha256 $TATSU_SHA256  (build-time only, not shipped)"
    echo "gcc                      : $(gcc --version | head -1)"
    echo "MSYS2 packages           : $(pacman -Q mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-libplist \
        mingw-w64-ucrt-x86_64-libimobiledevice-glue mingw-w64-ucrt-x86_64-libusbmuxd \
        mingw-w64-ucrt-x86_64-openssl | tr '\n' ';')"
    echo "configure                : --without-cython --disable-static --enable-shared (make install-strip)"
    echo "output sha256:"
    (cd "$OUT" && sha256sum libimobiledevice-1.0.dll ideviceinfo.exe)
} > "$OUT/BUILD-INFO.txt"
cat "$OUT/BUILD-INFO.txt"
