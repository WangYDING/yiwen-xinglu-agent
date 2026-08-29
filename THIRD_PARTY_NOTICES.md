# Third-party software, service, and model notices

This file records direct dependencies and optional integrations reviewed for
the local distribution. It is an attribution inventory, not a replacement for
upstream license texts or service terms. Transitive dependencies remain subject
to their own terms and should be reviewed for each release.

## Core Python dependencies

| Component | Project constraint / locally verified version | License recorded by official project metadata | Official source |
|---|---|---|---|
| HTTPX | `>=0.27,<1` / `0.28.1` | BSD-3-Clause | <https://pypi.org/project/httpx/> |
| MCP Python SDK | `==2.0.0` | MIT | <https://pypi.org/project/mcp/2.0.0/> |
| Pydantic | `>=2.8,<3` / `2.13.4` | MIT | <https://pypi.org/project/pydantic/> |
| python-dotenv | `>=1.0,<2` / `1.2.2` | BSD-3-Clause | <https://pypi.org/project/python-dotenv/1.2.2/> |

The public package does not vendor these libraries; installers resolve them as
normal Python dependencies.

## Development and build dependency

| Component | Project constraint / locally verified version | License | Official source |
|---|---|---|---|
| pytest | `>=7.4,<9` / `8.4.2` | MIT | <https://pypi.org/project/pytest/> |
| build | `>=1.2,<2` / `1.5.0` | MIT | <https://pypi.org/project/build/1.5.0/> |
| wheel | `>=0.45,<1` / `0.47.0` | MIT | <https://pypi.org/project/wheel/0.47.0/> |

Exact dependency versions can vary within the declared project constraints and
should be captured by the build environment used for each release.

## Optional local Embedding stack

The following packages are not installed by the core dependency set and are
not needed for manual/Fake play, MCP, or M5 acceptance.

| Component | Optional constraint / locally verified version | License identity | Official source |
|---|---|---|---|
| NumPy | `2.4.6` | Compound expression recorded by PyPI metadata: BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | <https://pypi.org/project/numpy/2.4.6/> |
| safetensors | `0.8.0` | Local distribution includes the upstream license file; verify the installed distribution when preparing a release | <https://pypi.org/project/safetensors/0.8.0/> |
| sentence-transformers | `5.7.0` | Apache-2.0 | <https://pypi.org/project/sentence-transformers/5.7.0/> |
| PyTorch | `2.12.1` (`2.12.1+cu126` in the verified Windows environment) | BSD-3-Clause | <https://pypi.org/project/torch/2.12.1/> |
| Transformers | `4.57.6` | Apache-2.0 | <https://pypi.org/project/transformers/4.57.6/> |

## BGE-M3 model

- Repository: `BAAI/bge-m3`
- Frozen revision: `142964af7e05de16511657561de8e8750fc153a0`
- Official model page: <https://huggingface.co/BAAI/bge-m3/tree/142964af7e05de16511657561de8e8750fc153a0>
- License marker on the fixed model page: MIT
- Distribution status: model files are stored only in the Git-ignored local
  `runtime_models/` directory and are **not** included in Git, wheel, or sdist.

The fixed revision has no standalone `LICENSE` file in the downloaded project
whitelist. Review the model card and applicable redistribution requirements
before distributing model weights; this project does not distribute them.

## DeepSeek external service

DeepSeek is an optional external API service used only by explicitly authorized
experiments and the guarded `deepseek-v0` mode. It is not a Python dependency,
no provider code or model is redistributed, and no API Key is included. Use is
governed by DeepSeek's current service terms, privacy terms, model availability,
and pricing rather than this project's Apache-2.0 license.

- API documentation: <https://api-docs.deepseek.com/>
- Review the current service and privacy terms before publishing outputs from
  new experiments.

## Scope boundary

The project-owned narrative and documentation rights are described in
`CONTENT_RIGHTS.md`. Nothing in this inventory relicenses third-party software,
services, models, or the reserved project content.
