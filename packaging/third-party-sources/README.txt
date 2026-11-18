iPhone App Manager 1.0.1 - Third-party source code (MSYS2 source packages)
===========================================================================

This bundle accompanies the Windows release of iPhone App Manager 1.0.1 (installer and portable ZIP).
It holds the MSYS2 source packages for FIVE third-party components whose compiled files are bundled
in the release, in the folder  tools\libimobiledevice .

It does NOT cover any other component of the release (for example OpenSSL, zlib, libzip, bzip2, xz,
zstd, Python, Tcl/Tk, PyInstaller). Those are listed, with their own licences, in THIRD-PARTY-NOTICES.txt
in the release's "licenses" folder.

iPhone App Manager is an independent project. It is not made by, or affiliated with, Apple Inc.


WHAT IS IN THIS BUNDLE
----------------------
Five MSYS2 source packages (*.src.tar.zst), each with its detached signature (*.sig), plus
SHA256SUMS.txt. The archives and signatures are exactly as published by MSYS2; they have not been
renamed or changed.

  mingw-w64-ideviceinstaller-1.1.1-2.src.tar.zst
  mingw-w64-libimobiledevice-1.3.0-18.src.tar.zst
  mingw-w64-libplist-2.7.0-4.src.tar.zst
  mingw-w64-libimobiledevice-glue-1.3.2-1.src.tar.zst
  mingw-w64-libusbmuxd-2.1.1-1.src.tar.zst

Each archive is a zstd-compressed tar file. Inside it you will find:
  - PKGBUILD    the MSYS2 build recipe for that package
  - .SRCINFO    package metadata, including the upstream download address and SHA-256 checksums
  - the upstream source archive, unmodified, as downloaded by MSYS2
  - any patches that MSYS2 applies before building:
      ideviceinstaller        no patches
      libimobiledevice        7 patches (001 to 007)
      libplist                1 patch  (003-fix-py-soext.patch)
      libimobiledevice-glue   no patches
      libusbmuxd              2 patches (001, 002)

The upstream source archives are:
  ideviceinstaller-1.1.1.tar.gz, libimobiledevice-1.3.0.tar.gz, libplist-2.7.0.tar.bz2,
  libimobiledevice-glue-1.3.2.tar.bz2, libusbmuxd-2.1.1.tar.bz2  (all from github.com/libimobiledevice)

Where to find the same material online:
  MSYS2 source packages : https://repo.msys2.org/mingw/sources/
  MSYS2 package recipes : https://github.com/msys2/MINGW-packages
  Upstream projects     : https://github.com/libimobiledevice  and  https://www.libimobiledevice.org/


HOW THESE RELATE TO THE BUNDLED BINARIES
----------------------------------------
The binaries in tools\libimobiledevice were copied from an MSYS2 UCRT64 installation (the
mingw-w64-ucrt-x86_64-* packages of the same names and versions). The source packages here are the
MSYS2 source packages for those exact versions. The release build checks the SHA-256 of every bundled
file against values recorded when these sources were obtained, and an earlier comparison found the
bundled files byte-for-byte identical to the files inside the MSYS2 binary packages.

  Package (version)                 Provides in the release
  ideviceinstaller 1.1.1-2          ideviceinstaller.exe
  libimobiledevice 1.3.0-18         libimobiledevice-1.0.dll and ideviceinfo.exe
  libplist 2.7.0-4                  libplist-2.0.dll
  libimobiledevice-glue 1.3.2-1     libimobiledevice-glue-1.0.dll
  libusbmuxd 2.1.1-1                libusbmuxd-2.0.dll

IMPORTANT LIMITS OF THIS BUNDLE
  - The sources have NOT been rebuilt by the author of iPhone App Manager, and no claim is made that
    the binaries can be reproduced from them.
  - Several files in these packages belong to programs that are not part of the release (for example
    the other command-line tools of libimobiledevice and libusbmuxd). Only the files listed above are
    bundled.
  - This bundle is not legal advice and does not by itself state that any licence obligation is met.


LICENCES (from the licence headers and COPYING files in the upstream sources)
-----------------------------------------------------------------------------
THIRD-PARTY-NOTICES.txt in the release's "licenses" folder is the main notice. In summary:
  - ideviceinstaller: GNU General Public License v2 or later.
  - libimobiledevice (library and ideviceinfo): GNU Lesser General Public License v2.1 or later.
  - libplist: mainly LGPL v2.1 or later, with small parts under the MIT licence (src/time64.c,
    src/jsmn.c, src/jsmn.h). MSYS2's metadata also lists GPL-2.0-or-later; why has not been
    established, and THIRD-PARTY-NOTICES.txt keeps that qualification.
  - libimobiledevice-glue: LGPL v2.1 or later, with SHA code from LibTomCrypt under its own terms.
  - libusbmuxd (library): LGPL v2.1 or later.
The full licence texts and copyright notices are inside the upstream source archives (COPYING,
COPYING.LESSER, AUTHORS and the file headers).


HOW TO VERIFY AND LOOK INSIDE
-----------------------------
1. Check the hashes of the files against SHA256SUMS.txt, for example in PowerShell:
     Get-FileHash .\*.src.tar.zst, .\*.sig -Algorithm SHA256
2. Check a signature with GnuPG and the MSYS2 keyring, for example:
     gpg --verify mingw-w64-libplist-2.7.0-4.src.tar.zst.sig mingw-w64-libplist-2.7.0-4.src.tar.zst
   All five signatures were made by the MSYS2 development key "Christoph Reiter (MSYS2 development
   key)", fingerprint 5F94 4B02 7F7F E209 1985 AA2E FA11 531A A0AA 7F57.
3. To read an archive, use a tool that supports .tar.zst (7-Zip 23 or later, or  tar --zstd -xf <file>
   where available). Do not run the build scripts unless you understand what they do.
