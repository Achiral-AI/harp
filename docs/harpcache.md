# HarpCache
HarpCache is Harp's bounded, read-only local project-context cache. It gives local model responses enough repository context to answer project questions without relying on Warp's cloud-side codebase index for every request.
## Inputs
HarpCache is built from metadata already present in Warp's `/ai/multi-agent` protobuf request:
- `input.context.directory.pwd`
- `input.context.codebases[*].path`
- `input.context.project_rules[*].active_rule_files`
- `input.context.git.branch`
- `input.context.git.head`
The cache resolves the best matching codebase root, maps the host path into the container mount, and refuses to read outside `HARP_CACHE_HOST_ROOT`.
## What is cached
Each snapshot is keyed by repository root, branch, and head. The rendered context includes:
- repo name, root, current working directory, branch, and head
- the ignore files HarpCache applied
- a bounded file manifest
- important project files such as `README.md`, `AGENTS.md`, `WARP.md`, `.warpignore`, `.warpindexingignore`, `pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `Makefile`, and Compose files
- active project rules that Warp already sent in the request
- a small set of text snippets selected by matching prompt terms against file paths
HarpCache is intentionally not a vector database yet. It is a fast local grounding layer that keeps the read surface bounded.
## Bounds and safety
The Docker Compose stack mounts the project tree read-only:
```bash
HARP_CACHE_HOST_ROOT=/Users/sonicaarora/Projects
HARP_CACHE_CONTAINER_ROOT=/Users/sonicaarora/Projects
```
Runtime limits keep cache construction from blocking the chat stream:
- `HARP_CACHE_TTL_S`: snapshot lifetime, default `15`
- `HARP_CACHE_MAX_REPOS`: max in-memory snapshots, default `16`
- `HARP_CACHE_MAX_FILES`: max files walked per snapshot, default `600`
- `HARP_CACHE_MANIFEST_ENTRIES`: max manifest entries rendered, default `160`
- `HARP_CACHE_RELEVANT_FILES`: max prompt-relevant snippets, default `6`
- `HARP_CACHE_MAX_FILE_BYTES`: max file size read for snippets, default `64000`
- `HARP_CACHE_MAX_SNIPPET_CHARS`: max chars per snippet, default `4000`
- `HARP_CACHE_MAX_CONTEXT_CHARS`: max total rendered context chars, default `24000`
- `HARP_CACHE_WALK_TIME_BUDGET_S`: hard directory-walk time budget, default `0.25`
HarpCache also de-duplicates manifest entries so repeated filenames reported by a filesystem walk cannot expand the prompt.
## Ignore files
HarpCache applies root-level ignore files before adding files to the manifest or snippets:
- `.gitignore`
- `.warpignore`
- `.warpindexingignore`
- `.cursorignore`
- `.cursorindexingignore`
- `.codeiumignore`
The matcher supports common root-relative, directory-only, wildcard, and negated patterns. Ignore handling is deliberately conservative and currently only loads ignore files at the repository root.
## Prompt injection
When a request is served locally, Harp injects the rendered context as a system message before the user message:
```text
<HarpCache>
Use this read-only local project context to ground the answer...
...
</HarpCache>
```
Follow-up user queries with prior task history are also served locally now. Harp passes recent text-only conversation history into the local model so references like "as asked before" have context.
## Limitations
- HarpCache does not execute tools. It improves local model context, but real `read_files`, `grep`, `file_glob`, and `apply_file_diffs` tool execution remains future work.
- It reads text files only and skips binary files, large files, lockfiles, environment files, hidden directories, dependency directories, build outputs, and vendor trees.
- It does not persist snapshots across Harp restarts.
- It does not build embeddings or semantic indexes yet.
