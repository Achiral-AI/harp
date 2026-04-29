# Building patched Warp OSS

Harp needs to talk to a Warp client that has the `Channel::Oss` URL-override
patch applied (see [`patches/`](../patches)). This walks through what we hit
when building Warp OSS from source on macOS, including a few gotchas that
Warp's own `script/bootstrap` doesn't currently surface.

## Prerequisites

The bootstrap script (`./script/bootstrap` inside the Warp checkout) installs
most of what you need. **In addition** to whatever it pulls in, you need:

1. **The full Xcode app**, not just Command Line Tools. Bootstrap exits
   immediately with `Please install Xcode from the App Store before continuing.`
   if `/Applications/Xcode.app` is missing. The download is ~12 GB; do this
   first or in parallel with the rest of the steps below.
2. **`protoc`** (the Protocol Buffers compiler). Bootstrap does **not**
   install it, but the build later fails on the `warp_multi_agent_api` build
   script with:
   ```
   Could not find `protoc`. If `protoc` is installed, try setting the
   `PROTOC` environment variable to the path of the `protoc` binary.
   ```
   Fix:
   ```bash
   brew install protobuf
   ```
3. **A signed-in `gcloud` SDK.** Bootstrap calls
   `gcloud auth print-identity-token` and prompts for a browser login if
   that fails. You can either:
   - let bootstrap drive the browser flow when it gets there, or
   - run `gcloud auth login` ahead of time.
4. **Accepted Xcode license, at admin level.** The first time bootstrap runs
   `xcodebuild -runFirstLaunch` after a fresh Xcode install, it'll fail with:
   ```
   Agreeing to the Xcode and Apple SDKs license requires admin privileges,
   please accept the Xcode license as the root user
   (e.g. 'sudo xcodebuild -license').
   ```
   Run that exact command, page through the license, and type `agree`.

## Run order that works

Doing the steps below front-to-back avoids the back-and-forth we hit on the
first try:

```bash
# 1. From the Mac App Store, install Xcode (full app). This is the longest
#    step; you can start the rest in parallel while it downloads.

# 2. Install protoc up front:
brew install protobuf

# 3. Clone Warp OSS:
git clone https://github.com/warpdotdev/warp.git ~/Projects/warp
cd ~/Projects/warp

# 4. Apply the Channel::Oss URL-override patch from Harp:
git apply /path/to/harp/patches/0001-allow-oss-channel-server-url-override.patch

# 5. Once Xcode finishes downloading, accept its license at admin level:
sudo xcodebuild -license     # press space to scroll, type `agree`

# 6. Run bootstrap. It'll install rust, brew formulae, gcloud, cargo deps.
./script/bootstrap

# 7. If bootstrap exits early with "start a new terminal session" after
#    installing rust, just source cargo into the current shell and re-run:
source "$HOME/.cargo/env"
./script/bootstrap

# 8. Build and launch, pointed at Harp:
WARP_SERVER_ROOT_URL=http://127.0.0.1:8787 ./script/run
```

That last step is the long pole — first build of the Rust workspace is
30–60 minutes (or down to ~3 min on a warm cache).

## Things that look like errors but aren't

- **`Cannot access ssh://git@github.com/warpdotdev/warp-channel-config.git`**
  during `install_cargo_test_deps` and `install_cargo_release_deps`. That's
  an internal-only Warp repo. The wrapper handles the failure cleanly —
  you'll fall through to the OSS channel build (`warp-oss` binary,
  `WarpOss.app` bundle), which is exactly what we want.
- **`xcodebuild` Metal toolchain catalog fetch fails on first try.** Retry
  generally succeeds on its own.
- **`No .icon bundle found for oss channel`** during `cargo bundle`. The
  OSS channel doesn't ship adaptive icons; the warning is benign.

## What you get

The build produces a separate app, deliberately named differently from the
Warp you may already have installed:

| Build artifact | Location |
| --- | --- |
| Bundle | `target/debug/bundle/osx/WarpOss.app` |
| Binary | `target/debug/warp-oss` |
| Channel | `Oss` (separate data domain `dev.warp.WarpOss`) |

`WarpOss.app` is a totally separate macOS app from your existing
`/Applications/Warp.app`. Different bundle ID, different settings, different
login session. They coexist cleanly.

To install the OSS build alongside the regular Warp:

```bash
cp -R target/debug/bundle/osx/WarpOss.app /Applications/
```

## Logging in for the first time

The OSS channel has its own data domain, so it starts unauthenticated. With
Harp's auth-redirect handler in place (`src/harp/auth_redirect.py`),
clicking "Log in" or "Sign up" inside `WarpOss` opens your browser at
`http://127.0.0.1:8787/signup/remote?...`, Harp `302`s the browser to
`https://app.warp.dev/signup/remote?...`, you complete OAuth there, and
`app.warp.dev` redirects back into `warposs://login?token=...` which the
local app picks up.

If anything in that chain breaks, watch:

```bash
make logs                 # both harp + litellm
make stats | jq           # one snapshot of /ai/multi-agent decisions
```

The auth-redirect path is logged as `auth-redirect: <path> -> <url>` in
harp's logs.
