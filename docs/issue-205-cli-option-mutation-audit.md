# Issue 205: CLI option mutation audit

## Summary

This audit investigates two `mutmut` survivors in
`schwab_mcp.cli._common_options`. The targeted `mutmut` run reported both as
`survived`, but a fresh-import reproduction shows both mutations change
behavior. The pinned `mutmut` 3.8.0 worker lifecycle explains why ordinary
pytest collection can register Click commands before worker mutation
activation. A forked worker then inherits the already registered commands.

Do not treat these survivor labels as equivalence findings. Mutant 96 has not
been shown equivalent. This audit does not claim that all possible CLI option
mutations have been covered.

## Scope and safety

- Source snapshot: tracked files from `git archive HEAD` at commit
  `ffae6c34c61ba0fb4ced65761069cac53f612db8`.
- Locked dependencies: `uv.lock` pins `mutmut` 3.8.0. The image was built
  with Python 3.12.15 and `uv` 0.12.18.
- Container image: `localhost/issue-205-diag:locked`, image ID
  `38657a9074eff15fe17d719f329e4ecdc1aaca68dadedd0fd46f42c8d9b37d2d`,
  image digest `sha256:5a02066884fb751a04cc9dc83cb6d1bf7db059f9cede33d4a9e82a8b9b1d403c`.
- Podman version: 5.8.7.
- Image build had network access to install locked dependencies. All
  diagnostic execution used `--network=none --cap-drop=ALL
  --security-opt=no-new-privileges --user=10001:10001`.
- No host repository, home, credential, browser, DBus, or SSH mounts were
  used. Runtime environment contained only temporary HOME/cache settings.
- The mutation command had a 300-second timeout. Image build had a
  600-second timeout. No full mutation campaign was run.

## Mutmut configuration and selection

`pyproject.toml` configures `source_paths = ["src/schwab_mcp"]`, clears pytest
`addopts`, and selects `tests/` for collection. The isolated collection
command emitted 762 pytest node IDs. The captured list is
`/tmp/opencode/issue-205/final-artifacts/collect.stdout`.

The project selection was `tests/`, not a hand-selected CLI test list. The
available CLI-related IDs include:

- `tests/test_cli_auth.py::test_auth_command_uses_max_token_age`
- `tests/test_cli_auth.py::test_auth_command_returns_error_on_exception`
- `tests/test_cli_auth.py::test_cli_main_entrypoint_delegates_to_cli_group`
- `tests/test_cli_credentials.py` auth and server credential fallback,
  override, and missing-credential cases
- `tests/test_cli_server_write_modes.py` server option and write-mode cases

The campaign artifacts do not record the per-mutant subset of node IDs that
each worker actually executed. Therefore, 762 is the collected test set, not
a claim that all 762 ran for each mutant. Do not infer per-mutant test
selection beyond the captured artifacts.

## Reproduction setup

The successful build used tracked source only. From the repository root:

```sh
mkdir -p /tmp/opencode/issue-205/source
git archive HEAD | tar -x -C /tmp/opencode/issue-205/source
cat > /tmp/opencode/issue-205/Containerfile <<'EOF'
FROM python:3.12-slim
ENV UV_LINK_MODE=copy UV_CACHE_DIR=/tmp/uv-cache
WORKDIR /app
COPY . /app
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.12.18 \
    && uv sync --locked --all-groups
CMD ["uv", "run", "--locked", "--no-sync", "mutmut", "--help"]
EOF
timeout 600 podman build --pull=never \
  -f /tmp/opencode/issue-205/Containerfile \
  -t issue-205-diag:locked /tmp/opencode/issue-205/source
```

The build needed Git because the locked Schwab dependency is installed from
its pinned Git revision. The build had network access; build output and error
logs are under `/tmp/opencode/issue-205/logs/`.

## Targeted mutmut run

The locked project command was run from a temporary copy of the archived
source, with temporary `HOME` and cache directories:

```sh
timeout 300 uv run --locked --no-sync mutmut run \
  schwab_mcp.cli.x__common_options__mutmut_1 \
  schwab_mcp.cli.x__common_options__mutmut_96
uv run --locked --no-sync mutmut results --all true
uv run --locked --no-sync mutmut show schwab_mcp.cli.x__common_options__mutmut_1
uv run --locked --no-sync mutmut show schwab_mcp.cli.x__common_options__mutmut_96
```

The exact runtime policy and command sequence were:

```sh
podman run --name issue205-final --network=none --cap-drop=ALL \
  --security-opt=no-new-privileges --user=10001:10001 \
  -e UV_CACHE_DIR=/tmp/cache -e HOME=/tmp/home \
  --entrypoint /bin/sh issue-205-diag:locked -c '
    set +e
    mkdir -p /tmp/work /tmp/artifacts /tmp/home
    cp -a /app/. /tmp/work/
    cd /tmp/work
    timeout 300 uv run --locked --no-sync mutmut run \
      schwab_mcp.cli.x__common_options__mutmut_1 \
      schwab_mcp.cli.x__common_options__mutmut_96 \
      > /tmp/artifacts/run.stdout 2> /tmp/artifacts/run.stderr
    echo "$?" > /tmp/artifacts/run.exit
    uv run --locked --no-sync mutmut results --all true \
      > /tmp/artifacts/results.stdout 2> /tmp/artifacts/results.stderr
    echo "$?" > /tmp/artifacts/results.exit
    uv run --locked --no-sync mutmut show \
      schwab_mcp.cli.x__common_options__mutmut_1 \
      > /tmp/artifacts/mutant-1.show
    uv run --locked --no-sync mutmut show \
      schwab_mcp.cli.x__common_options__mutmut_96 \
      > /tmp/artifacts/mutant-96.show
    uv run --locked --no-sync pytest --collect-only -q \
      -p no:randomly -p no:random-order tests/ -o addopts= \
      > /tmp/artifacts/collect.stdout 2> /tmp/artifacts/collect.stderr
    echo "$?" > /tmp/artifacts/collect.exit
  '
podman cp issue205-final:/tmp/artifacts \
  /tmp/opencode/issue-205/reproduced-artifacts
podman inspect issue205-final --format '{{.State.ExitCode}} {{.State.OOMKilled}}'
podman rm issue205-final
```

Inside the container, `/app` was copied to writable `/tmp/work`, then the
commands above ran from `/tmp/work`. No source files in the worktree were
modified. The targeted run generated the mutant inventory for 31 files
(7,022 total mutants), but ran only the two named mutants. Both were reported
as `survived`; the run and result commands exited 0.

### Mutant 1

`schwab_mcp.cli.x__common_options__mutmut_1` replaces the first
`click.option("--base-url", ...)(function)` application with
`function = None`. The saved mutmut diff is
`/tmp/opencode/issue-205/final-artifacts/schwab_mcp.cli.x__common_options__mutmut_1.show`.

### Mutant 96

`schwab_mcp.cli.x__common_options__mutmut_96` changes the token-path default
from `tokens.token_path(APP_NAME)` to `tokens.token_path(None)`. The saved
mutmut diff is
`/tmp/opencode/issue-205/final-artifacts/schwab_mcp.cli.x__common_options__mutmut_96.show`.

## Fresh-import and inherited-command reproduction

The separate source diagnostic modified only a temporary `/tmp/work` copy of
`cli.py`; it did not use mutmut's mutation trampoline. It ran each source
variant in a fresh Python interpreter and then ran a fork simulation that
imported baseline `cli` first, changed only the on-disk source, and forked a
child with the already registered Click command objects.

Observed outcomes:

| Case | Fresh import | Baseline commands inherited before fork |
| --- | --- | --- |
| Baseline | Import succeeds; `auth --help` includes `--base-url`; token default is `/tmp/home/.local/share/schwab-mcp/token.yaml`. | Baseline options and token default remain registered. |
| Mutant 1 | Import fails with `AttributeError: 'NoneType' object has no attribute '__click_params__'` while applying the callback-url option. | `--base-url` remains registered, and the baseline token default remains. |
| Mutant 96 | Import succeeds; token default is `/tmp/home/.local/share/token.yaml`. | The original Schwab-MCP token default remains registered. |

The source diagnostic artifacts are under
`/tmp/opencode/issue-205/timing-artifacts/artifacts/`; the fork output is
`/tmp/opencode/issue-205/logs/timing.stdout`. The script is
`/tmp/opencode/issue-205/scripts/import-timing.py`.

The source diagnostic was run separately with the same no-network runtime
restrictions. The host script was copied into the container, not mounted:

```sh
podman create --name issue205-timing --network=none --cap-drop=ALL \
  --security-opt=no-new-privileges --user=10001:10001 \
  -e UV_CACHE_DIR=/tmp/cache -e HOME=/tmp/home \
  --entrypoint /bin/sh issue-205-diag:locked -c \
  'mkdir -p /tmp/work /tmp/home /tmp/artifacts; \
   cp -a /app/. /tmp/work/; cd /tmp/work; \
   uv run --locked --no-sync python /tmp/import-timing.py'
podman cp /tmp/opencode/issue-205/scripts/import-timing.py \
  issue205-timing:/tmp/import-timing.py
podman start -a issue205-timing
podman cp issue205-timing:/tmp/artifacts \
  /tmp/opencode/issue-205/timing-artifacts
podman inspect issue205-timing --format '{{.State.ExitCode}} {{.State.OOMKilled}}'
podman rm issue205-timing
```

This demonstrates that the mutations matter when active before import, and
that already-created Click command objects retain baseline registrations. It
is not itself a mutmut-trampoline experiment and must not be presented as
proof of the exact state of a mutmut worker. The separate targeted mutmut
run's actual survivor status is recorded above.

The pinned `mutmut` 3.8.0 source commit
`14a7230049a5c8abd90c2bb0f7438e30da6471f5` provides the worker-lifecycle
explanation: `mutmut/workers/isolation.py:853-870` forks workers,
`mutmut/runners/harness.py:154-158` uses the test harness, and
`mutmut/__main__.py:319-330` performs stats collection. In this lifecycle,
pytest collection imports the application and registers Click commands
before mutation workers run; import-time mutation hits can be accounted for
at test teardown, while forked workers inherit the registered baseline
commands. This is why a survivor label here does not show that the changed
CLI behavior was tested.

## Completed behavioral coverage and remaining limitations

`tests/test_cli_common_options.py` now adds four parameterized scenarios,
each exercised for both `auth` and `server`:

1. Help output lists the shared options, including `--base-url` and
   `--token-path`.
2. Default callback and base URLs reach the client-construction boundary.
3. Credential and URL values from environment variables reach that boundary.
4. Explicit CLI values take precedence over environment values.

These eight command scenarios reuse the Click group imported during pytest
collection. They protect ordinary option registration and forwarding, but do
not cure the mutmut timing issue: they do not import the application after a
mutant becomes active. A fresh-process test that covers import-time
registration remains a limitation and follow-up.

Existing auth/server command tests that exercise token paths pass an
explicit `--token-path`. The new tests do not cover the default token path.
That default remains an uncovered behavioral case because import-time
isolation affects the existing test boundary; a fresh-process default-path
check remains a follow-up, not a completed test.

Validation for the focused CLI set ran in the safe Podman setup. The offline
runtime command covered `tests/test_cli_auth.py`,
`tests/test_cli_credentials.py`, `tests/test_cli_server_write_modes.py`, and
`tests/test_cli_common_options.py`: 46 passed, with two dependency
deprecation warnings. Ruff format and lint passed. Configured pyright reported
0 errors, 0 warnings, and 0 informations. Node was provisioned in the image
build; the validation runtime was offline. Captured output and status are in
`/tmp/opencode/issue-205/cli-artifacts/followup-validation/`;
`final-runtime.log` records the final checks and `final-runtime.exit` contains `0`.

## Artifact and evidence limits

The successful targeted run stdout, stderr, exit code, results, diffs, and
collected IDs are in `/tmp/opencode/issue-205/final-artifacts/`. The run
exited 0, stderr was empty, and the result report says both targets
`survived`. The container exited 0 and was not OOM-killed.

The successful run did not retain a process-list snapshot. An earlier
snapshot attempt recorded only start and end timestamps because `ps` was not
installed in the image; that attempt also preceded correction of the
temporary `HOME` setup and is not evidence for the successful run. The
successful run was bounded by `timeout 300`, but its individual worker
process snapshots are unavailable.

No conclusion is made that mutant 96 is equivalent. No full mutation
campaign, production edit, test edit, or repository commit was part of the
mutation diagnostic phase. The later behavioral test additions are described above.
