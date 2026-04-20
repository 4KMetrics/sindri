# Changelog

## [0.1.1](https://github.com/4KMetrics/sindri/compare/v0.1.0...v0.1.1) (2026-04-20)


### Features

* **cli:** add archive subcommand ([4d00181](https://github.com/4KMetrics/sindri/commit/4d001811da7d7f281161a28fc70ead9074b42651))
* **cli:** add check-termination subcommand ([c93ccdb](https://github.com/4KMetrics/sindri/commit/c93ccdb673ae2c7b52ac9408339dcec6ba211529))
* **cli:** add detect-mode subcommand ([d596cb3](https://github.com/4KMetrics/sindri/commit/d596cb3f6b84c67d867cd9f9242d6e90ff597d06))
* **cli:** add generate-pr-body subcommand ([e5e629c](https://github.com/4KMetrics/sindri/commit/e5e629cdcc139162e36f08a0541fe2faf85e1830))
* **cli:** add init subcommand for end-to-end run setup ([4b766f7](https://github.com/4KMetrics/sindri/commit/4b766f723b538c95c3bfe9419690785c95b76ad1))
* **cli:** add pick-next subcommand ([03c21bd](https://github.com/4KMetrics/sindri/commit/03c21bdbf53514cfbc7599039b0b03cf83585afe))
* **cli:** add read-state subcommand ([6b81247](https://github.com/4KMetrics/sindri/commit/6b81247d7e6b2b9956eaaa9279a7c66fb912f6cd))
* **cli:** add record-result subcommand ([11c3c39](https://github.com/4KMetrics/sindri/commit/11c3c39b6ab0e95c7867ed4ef8f980487adc62fc))
* **cli:** add status subcommand ([48dd080](https://github.com/4KMetrics/sindri/commit/48dd08057af680c88ff9ac309de4ef45e9519c13))
* **cli:** add validate-benchmark subcommand ([5a4eb0f](https://github.com/4KMetrics/sindri/commit/5a4eb0f01e1ecd1f7272e085291a1dc505e71491))
* **cli:** scaffold argparse dispatcher with subcommand registry ([f49b82f](https://github.com/4KMetrics/sindri/commit/f49b82f44135ef1331277c1fc18135d8033ef09d))
* **core:** add git subprocess wrappers ([444abe6](https://github.com/4KMetrics/sindri/commit/444abe65db19fcb6854ea3854f83011ab59ad82d))
* **core:** add local/remote mode detection ([7fa9710](https://github.com/4KMetrics/sindri/commit/7fa971016022543713ea4c06567b4dce6d6c9068))
* **core:** add METRIC line parser ([a0a325f](https://github.com/4KMetrics/sindri/commit/a0a325fcedd3e7fc9982a415ca172d51a9ba14a8))
* **core:** add noise floor, confidence ratio, CV stats ([fb2ddea](https://github.com/4KMetrics/sindri/commit/fb2ddeab446470cb1d0c62b3cfdbc4937d4bee6b))
* **core:** add pool ordering and termination predicates ([c96168a](https://github.com/4KMetrics/sindri/commit/c96168ab0aa8f91d3efa4ecb7aaf75eeeb833928))
* **core:** add PR body markdown renderer ([b532b3d](https://github.com/4KMetrics/sindri/commit/b532b3dc86f174ed8ca1e6c55238adf29d363e2c))
* **core:** add pydantic models for state, jsonl, subagent result ([e5d1308](https://github.com/4KMetrics/sindri/commit/e5d1308abe8cf80aadf27211348bbd5f7df3c437))
* **core:** add state.py for sindri.md and sindri.jsonl I/O ([bc3131d](https://github.com/4KMetrics/sindri/commit/bc3131d643447bd26ee36ce24351d46fab32be91))
* **core:** add termination decision table composing predicates ([6fc4f83](https://github.com/4KMetrics/sindri/commit/6fc4f830b0c93ace249d2cb508679142dc7ca96a))
* initial drop — design spec + Python core + CLI (Plan 1) ([10db076](https://github.com/4KMetrics/sindri/commit/10db076fd4d4026b3832b36dfae6cefe3f0b713d))
* **plugin:** sindri plugin artifacts (Plan 2) ([#2](https://github.com/4KMetrics/sindri/issues/2)) ([62cdb0f](https://github.com/4KMetrics/sindri/commit/62cdb0fa59f1aeeb558b8a456a62cd5250b55934))


### Bug Fixes

* **cli:** init fails fast on taken branch; goal regex uses fullmatch ([c92761f](https://github.com/4KMetrics/sindri/commit/c92761f7962e723af15f6755d649fe13f945d5af))
* **cli:** refuse unsafe slugs when archiving ([3b9b4e6](https://github.com/4KMetrics/sindri/commit/3b9b4e6d59b9f8de315dbbf94daf7e6665ff2451))
* code-review findings (StateIOError guards + wget localhost parity) ([6bd7257](https://github.com/4KMetrics/sindri/commit/6bd72578cf0a5c10a2cf390c9bbf681dbb8dce7c))
* **state:** surface malformed jsonl skips on stderr; clarify atomicity comment ([660b143](https://github.com/4KMetrics/sindri/commit/660b1432f44a63276584bfa546b9867a45db3054))
* **validators:** tz-aware started_at; None-sentinel mode-based defaults ([480ede3](https://github.com/4KMetrics/sindri/commit/480ede3e68246d3ca3969962432ca17671e0d24d))


### Documentation

* add initial design spec for sindri v1 ([f797819](https://github.com/4KMetrics/sindri/commit/f7978195ea9a0cff15aff22231d2aa951b133034))
* add Plan 1 — sindri Python core + CLI implementation ([6be79c6](https://github.com/4KMetrics/sindri/commit/6be79c603c66cd2093b75bc8a048b32aabbf3dcb))
* add Table of Contents to sindri design spec ([fcf2af9](https://github.com/4KMetrics/sindri/commit/fcf2af9f4b17b30a9da0af14403355219d21c6ec))
* clarify benchmark scaffolding is sindri's job, not a separate chat ([c4eadd5](https://github.com/4KMetrics/sindri/commit/c4eadd57f670a3342f62cd5941fd37457e610614))
* drop personal-roadmap framing from sindri spec ([f8ba7df](https://github.com/4KMetrics/sindri/commit/f8ba7dfd712e75b09f859d900e9267f6775cf7bb))
* replace ratchet metaphor with blacksmith-native language ([f5cc5b1](https://github.com/4KMetrics/sindri/commit/f5cc5b1d50349d1fd3eda4379f304fcac4be4b0b))
* switch user benchmark scripts from shell to Python ([eb647d0](https://github.com/4KMetrics/sindri/commit/eb647d0df634f6c1ba2ad3a0deb8dc4f2620fbf1))
