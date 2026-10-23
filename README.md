# Droidian kernel for Samsung Galaxy S10e

Kernel adaptation for **Samsung Galaxy S10e SM-G970F / beyond0lte (Exynos 9820)**,
using Droidian and an Android 12 / Halium API 32 vendor stack.
Other Exynos 9820 devices have not been validated by this port.

Based on LineageOS `lineage-23.2`, commit
`a412cfaf86b980ce35cae96a35f678c8ea551575` (Linux 4.14.356-openela-rc1).
The original kernel documentation remains in [README](README).

## Port changes

- Initialize the SAR ramdisk offset, allowing the Droidian initramfs to start.
- Preserve the default return value for empty security-hook lists, fixing the
  AF_UNIX/SO_PASSSEC failure found during bring-up.
- Accept an unavailable Binder transaction security context when SELinux is
  disabled, while retaining other permission/allocation failures.
- Translate the Samsung Android 12 DECON ioctl layout without removing the
  newer LineageOS ABI, enabling the vendor HWC display path.
- Include Halium/Droidian configuration, EROFS and the S10e boot arguments.
- Build `dm-crypt.ko` for early LUKS unlock, and a patched v4l2loopback 0.12.7
  exposing `capture_clients` for the userspace camera bridge.

The source fixes were used on the working phone kernel. New CI bundles require
their own physical-device validation; building successfully does not establish
that boot, suspend, calls or cameras work. This port currently boots with SELinux
disabled, matching its existing Droidian integration.

## Build locally

The compiler, builder image and camera-module sources are pinned in
[droidian/sources.lock.json](droidian/sources.lock.json). Downloaded inputs are
verified with SHA-256. Gitiles regenerates toolchain archive timestamps, so
`toolchain-files.json` pins every file's contents, mode and symlink target while
allowing those timestamps to vary. The v4l2loopback archive is pinned as a whole.
Config fragments are included in this repository; the
upstream Halium/Droidian fragments come from `common_fragments` commit
`438e885f38dba4840677b5b4f8bf5166e21e2b32`.

On an x86-64 Linux machine with Docker:

```sh
builder=$(python3 -c 'import json; print(json.load(open("droidian/sources.lock.json"))["builder_image"])')
docker run --rm -v "$PWD:/src" -w /src "$builder" bash -c \
  'git config --global --add safe.directory /src; ./droidian/install-build-deps.sh && ./droidian/build.sh'
```

Docker may create root-owned build files in the checkout. Build products stay in
`.build/`, downloaded archives in `.cache/`, and release files in `dist/`; all are
ignored by Git. `S10E_JOBS` controls parallelism. The same build script is used in
Actions; it does not access or flash a connected phone.

`SOURCE_DATE_EPOCH` and build identity come from the source commit. The kernel
release includes the commit ID so modules from different kernel commits are not
silently mixed. Rebuilding from a tag retains that same release string.

## Actions and Build releases

- A push to `main` builds and validates the bundle, then publishes **Build 1**,
  **Build 2**, etc. Tags are `build-1`, `build-2`, etc.
- Pull requests run the build and checks without release permissions.
- **Run workflow** on `main` can publish a build or only produce CI artifacts.
- Release numbering uses existing Build tags/releases, independently of CI run
  numbers. Publishing is serialized. Rerunning the same source commit reuses its
  release or resumes its incomplete draft.
- Releases initially have the **pre-release** flag because device testing is
  still required. A tested Build can be promoted manually without renaming it.
- Temporary CI artifacts expire after 14 days; releases are the distribution
  channel for retained bundles.

The default GitHub branch should be `main` so manual Actions runs are available.
The release job is restricted to this port's GitHub repository and `main`.

## Release contents and OS integration

| File | Purpose |
| --- | --- |
| `Image` | Uncompressed arm64 kernel |
| `dtbs.tar.gz` | Compiled DTB/DTBO files with their original relative paths |
| `modules.tar.gz` | Matching `/lib/modules/<kernel-release>/` tree, including dm-crypt and v4l2loopback |
| `kernel.config` | Resolved kernel configuration |
| `Module.symvers` | Symbol versions for additional modules |
| `sources.lock.json` | Pinned build inputs and provenance |
| `toolchain-files.json` | Exact toolchain file checksums and metadata |
| `build-info.json` | Source commit, compiler, kernel release and validation status |
| `SHA256SUMS` | Checksums of the files above |

This is **not a flashable boot image**. The Droidian OS repository must select a
specific Build and checksum, construct a matching initramfs/`boot.img`, install
the module tree and run `depmod` for its kernel release. Early unlock must use
the `dm-crypt.ko` from that same Build. Device-tree partition packaging is also an
OS-installation responsibility; raw DTBs are not Samsung partition images.

No stock proprietary vendor images, personal data, SSH keys or user credentials
are included. Userspace graphics/audio/camera fixes belong to the OS adaptation
repository, rather than this kernel bundle.

The Linux kernel and imported components retain their original licenses; see
[COPYING](COPYING) and the per-file notices. The release tag identifies the
corresponding kernel sources; v4l2loopback sources and its local patch are pinned
by the lock file and included patch.
