iPhone App Manager 1.0.2 - Third-party source code
===================================================

This bundle accompanies the Windows release of iPhone App Manager 1.0.2 (installer and portable ZIP).
It holds the source of FIVE third-party components whose compiled files are bundled in the release, in
the folder  tools\libimobiledevice :

  - four MSYS2 source packages (ideviceinstaller, libplist, libimobiledevice-glue, libusbmuxd), and
  - the upstream libimobiledevice 1.4.0 release tarball, with the script that builds it.

It does NOT cover any other component of the release (for example OpenSSL, zlib, libzip, bzip2, xz,
zstd, Python, Tcl/Tk, PyInstaller). Those are listed, with their own licences, in THIRD-PARTY-NOTICES.txt
in the release's "licenses" folder.

iPhone App Manager is an independent project. It is not made by, or affiliated with, Apple Inc.


WHAT IS IN THIS BUNDLE
----------------------
README.txt and SHA256SUMS.txt, plus:

A. Four MSYS2 source packages (*.src.tar.zst), each with its detached signature (*.sig), exactly as
   published by MSYS2; they have not been renamed or changed:

     mingw-w64-ideviceinstaller-1.1.1-2.src.tar.zst
     mingw-w64-libplist-2.7.0-4.src.tar.zst
     mingw-w64-libimobiledevice-glue-1.3.2-1.src.tar.zst
     mingw-w64-libusbmuxd-2.1.1-1.src.tar.zst

   Each archive is a zstd-compressed tar file. Inside it you will find:
     - PKGBUILD    the MSYS2 build recipe for that package
     - .SRCINFO    package metadata, including the upstream download address and SHA-256 checksums
     - the upstream source archive, unmodified, as downloaded by MSYS2
     - any patches that MSYS2 applies before building:
         ideviceinstaller        no patches
         libplist                1 patch  (003-fix-py-soext.patch)
         libimobiledevice-glue   no patches
         libusbmuxd              2 patches (001, 002)

B. The upstream libimobiledevice source and the script that builds it (NOT an MSYS2 package):

     libimobiledevice-1.4.0.tar.bz2     the upstream 1.4.0 release tarball, unmodified
                                        (https://github.com/libimobiledevice/libimobiledevice/releases/tag/1.4.0)
     libtatsu-1.0.5.tar.bz2             upstream libtatsu 1.0.5 - a BUILD-TIME prerequisite only: the
                                        libimobiledevice configure script requires it, but nothing from it is in the
                                        release (the built files do not import libtatsu.dll or libcurl)
     build_libimobiledevice.sh          the script that builds libimobiledevice-1.0.dll and ideviceinfo.exe
                                        from those two tarballs in an MSYS2 UCRT64 shell

   Upstream publishes no signature for these two tarballs, so none is included; SHA256SUMS.txt records their
   SHA-256 values and the build script checks them before building.

Where to find the same material online:
  MSYS2 source packages : https://repo.msys2.org/mingw/sources/
  MSYS2 package recipes : https://github.com/msys2/MINGW-packages
  Upstream projects     : https://github.com/libimobiledevice  and  https://www.libimobiledevice.org/


HOW THESE RELATE TO THE BUNDLED BINARIES
----------------------------------------
  Source (version)                  Provides in the release
  ideviceinstaller 1.1.1-2          ideviceinstaller.exe                       (MSYS2 binary)
  libplist 2.7.0-4                  libplist-2.0.dll                           (MSYS2 binary)
  libimobiledevice-glue 1.3.2-1     libimobiledevice-glue-1.0.dll              (MSYS2 binary)
  libusbmuxd 2.1.1-1                libusbmuxd-2.0.dll                         (MSYS2 binary)
  libimobiledevice 1.4.0            libimobiledevice-1.0.dll and ideviceinfo.exe (built by the author's script)

The four MSYS2 components were copied from an MSYS2 UCRT64 installation (the mingw-w64-ucrt-x86_64-* packages
of the same names and versions); the sources here are the MSYS2 source packages for those exact versions.
The author did not rebuild them, and an earlier comparison found the bundled files byte-for-byte identical to
the files inside the MSYS2 binary packages.

libimobiledevice-1.0.dll and ideviceinfo.exe are different: MSYS2 only has libimobiledevice 1.3.0, whose
network-device connection code does not work on Windows (fixed upstream in 1.4.0), so these two files were
built by the author from the unmodified 1.4.0 tarball with the script build_libimobiledevice.sh and the MSYS2
UCRT64 compiler. No patches are applied. Two builds in different folders produced byte-identical files. The
release build checks the SHA-256 of every bundled file against values recorded in the project, including these
two. The script was run with the MSYS2 packages recorded in packaging\third-party-binaries\libimobiledevice-1.4.0\
BUILD-INFO.txt (gcc 16.2.0-7, libplist 2.7.0-4, libimobiledevice-glue 1.3.2-1, libusbmuxd 2.1.1-1, openssl
4.1.0-1); a different compiler or library version may give different bytes.

IMPORTANT LIMITS OF THIS BUNDLE
  - No claim is made that the four MSYS2 binaries can be reproduced from their sources by the author.
  - Several files in these sources belong to programs that are not part of the release (for example the
    other command-line tools of libimobiledevice and libusbmuxd). Only the files listed above are bundled.
  - This bundle is not legal advice and does not by itself state that any licence obligation is met.


LICENCES (from the licence headers and COPYING files in the upstream sources)
-----------------------------------------------------------------------------
THIRD-PARTY-NOTICES.txt in the release's "licenses" folder is the main notice. In summary:
  - ideviceinstaller: GNU General Public License v2 or later.
  - libimobiledevice (library and ideviceinfo): GNU Lesser General Public License v2.1 or later. All 64
    source and header files compiled into the two bundled files carry an LGPL-2.1-or-later header; the one
    GPL-licensed program in the upstream tree (tools/idevicesetlocation.c) is not part of the release.
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
     Get-FileHash .\*.src.tar.zst, .\*.sig, .\*.tar.bz2, .\*.sh -Algorithm SHA256
2. Check an MSYS2 signature with GnuPG and the MSYS2 keyring, for example:
     gpg --verify mingw-w64-libplist-2.7.0-4.src.tar.zst.sig mingw-w64-libplist-2.7.0-4.src.tar.zst
   All four signatures were made by the MSYS2 development key "Christoph Reiter (MSYS2 development
   key)", fingerprint 5F94 4B02 7F7F E209 1985 AA2E FA11 531A A0AA 7F57.
3. To read an MSYS2 archive, use a tool that supports .tar.zst (7-Zip 23 or later, or  tar --zstd -xf <file>
   where available). The upstream tarballs are ordinary .tar.bz2 files.
4. To rebuild libimobiledevice, install MSYS2 (https://www.msys2.org), open its UCRT64 shell, install the
   packages named at the top of build_libimobiledevice.sh, and run:
     build_libimobiledevice.sh <folder-with-the-two-tarballs> <empty-work-folder> <output-folder>
   Do not run build scripts unless you understand what they do.
