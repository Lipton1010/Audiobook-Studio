# Optional Chatterbox runtime notices

This optional pack is downloaded only after explicit selection and terms review. No model or narrator environment belongs in the core installer.

The original English Chatterbox code and publisher model card declare MIT. Preserve upstream notices and the pinned model README. Dependencies retain their own terms; this is not a blanket commercial-use clearance. In particular pykakasi declares GPL-3.0-or-later and soxr LGPL-2.1-or-later. Downloading a separate runtime does not itself settle all licensing obligations. Installed distributions retain their license files under their package metadata.

Only use voice references you have permission to use. The existing Storybird renderer substitutes its historical watermark stub; do not promise that Storybird exports contain upstream PerTh watermarks.

The Windows SoundFile wheel additionally includes libsndfile and its LGPL-2.1 COPYING notice under `_soundfile_data`; retain it alongside the SoundFile BSD license. Windows-native wheels must be selected rather than generic no-binary wheels.

## Maintenance and watermark status

The official Chatterbox README, checked 2026-11-10, states the project was retired in August 2026 and is no longer maintained or supported. Archived MIT availability is not a maintenance commitment: https://github.com/resemble-ai/chatterbox/blob/master/README.md .

Pinned chatterbox-tts 0.1.7 constructs the PerTh watermarker by default. Storybird retains its existing no-op watermark adapter; upstream watermark claims must not be applied to Storybird exports. The isolated upstream smoke used the default PerTh implementation, not Storybird's worker.

## Official artifact provenance

Exact artifact hashes are in install/requirements-chatterbox-win311.lock.txt. The table below links the sources; review included wheel/source license files for bundled third-party notices. Registry license metadata is not a complete legal audit.

- Deprecated: MIT. Source: https://files.pythonhosted.org/packages/84/d0/205d54408c08b13550c733c4b85429e7ead111c7f0014309637425520a9a/deprecated-1.3.1-py2.py3-none-any.whl
- Jinja2: Review package notices. Source: https://files.pythonhosted.org/packages/62/a1/3d680cbfd5f4b8f15abc1d571870c5fc3e594bb582bc3b64ea099db13e56/jinja2-3.1.6-py3-none-any.whl
- MarkupSafe: BSD-3-Clause. Source: https://files.pythonhosted.org/packages/83/8a/4414c03d3f891739326e1783338e48fb49781cc915b2e0ee052aa490d586/markupsafe-3.0.3-cp311-cp311-win_amd64.whl
- PyYAML: MIT. Source: https://files.pythonhosted.org/packages/da/e3/ea007450a105ae919a72393cb06f122f288ef60bba2dc64b26e2646fa315/pyyaml-6.0.3-cp311-cp311-win_amd64.whl
- Pygments: BSD-2-Clause. Source: https://files.pythonhosted.org/packages/f4/7e/a72dd26f3b0f4f2bf1dd8923c85f7ceb43172af56d63c7383eb62b332364/pygments-2.20.0-py3-none-any.whl
- aiofiles: Apache-2.0. Source: https://files.pythonhosted.org/packages/a5/45/30bb92d442636f570cb5651bc661f52b610e2eec3f891a5dc3a4c3667db0/aiofiles-24.1.0-py3-none-any.whl
- annotated-doc: MIT. Source: https://files.pythonhosted.org/packages/1e/d3/26bf1008eb3d2daa8ef4cacc7f3bfdc11818d111f7e2d0201bc6e3b49d45/annotated_doc-0.0.4-py3-none-any.whl
- annotated-types: Review package notices. Source: https://files.pythonhosted.org/packages/78/b6/6307fbef88d9b5ee7421e68d78a9f162e0da4900bc5f5793f6d3d0e34fb8/annotated_types-0.7.0-py3-none-any.whl
- antlr4-python3-runtime: BSD. Source: https://files.pythonhosted.org/packages/3e/38/7859ff46355f76f8d19459005ca000b6e7012f2f1ca597746cbcd1fbfe5e/antlr4-python3-runtime-4.9.3.tar.gz (source archive; built with pinned setuptools/wheel)
- anyio: MIT. Source: https://files.pythonhosted.org/packages/b0/7b/90df4a0a816d98d6ea26f559d87836d494a2cf1fcf063be67df50a7bcc30/anyio-4.14.1-py3-none-any.whl
- audioread: MIT. Source: https://files.pythonhosted.org/packages/7e/16/fbe8e1e185a45042f7cd3a282def5bb8d95bb69ab9e9ef6a5368aa17e426/audioread-3.1.0-py3-none-any.whl
- brotli: MIT. Source: https://files.pythonhosted.org/packages/02/8b/ecb5761b989629a4758c394b9301607a5880de61ee2ee5fe104b87149ebc/brotli-1.2.0-cp311-cp311-win_amd64.whl
- catalogue: MIT. Source: https://files.pythonhosted.org/packages/9e/96/d32b941a501ab566a16358d68b6eb4e4acc373fab3c3c4d7d9e649f7b4bb/catalogue-2.0.10-py3-none-any.whl
- certifi: MPL-2.0. Source: https://files.pythonhosted.org/packages/ef/2f/c5464532e965badff2f4c4c1a3a83f5697f0d7c407ed0cda44aaa99bb451/certifi-2026.6.17-py3-none-any.whl
- cffi: MIT. Source: https://files.pythonhosted.org/packages/ae/8f/dc5531155e7070361eb1b7e4c1a9d896d0cb21c49f807a6c03fd63fc877e/cffi-2.0.0-cp311-cp311-win_amd64.whl
- cfgv: MIT. Source: https://files.pythonhosted.org/packages/db/3c/33bac158f8ab7f89b2e59426d5fe2e4f63f7ed25df84c036890172b412b5/cfgv-3.5.0-py2.py3-none-any.whl
- charset-normalizer: MIT. Source: https://files.pythonhosted.org/packages/20/d9/5f67790f06b735d7c7637171bbfd89882ad67201891b7275e51116ed8207/charset_normalizer-3.4.7-cp311-cp311-win_amd64.whl
- chatterbox-tts: See full package license and bundled third-party notices. Source: https://files.pythonhosted.org/packages/54/37/11a7f06983bfd5ebba71eb2caa6660941b17b31f3c49d4a5fe9e1e804d31/chatterbox_tts-0.1.7-py3-none-any.whl
- click: BSD-3-Clause. Source: https://files.pythonhosted.org/packages/fb/e2/79c688af8b210d232694e31e59da9f6ec747bae31c3f5946e4e9b98860d5/click-8.4.2-py3-none-any.whl
- colorama: Review package notices. Source: https://files.pythonhosted.org/packages/d1/d6/3965ed04c63042e047cb6a3e6ed1a63a35087b6a609aa3a15ed8ac56c221/colorama-0.4.6-py2.py3-none-any.whl
- conformer: MIT. Source: https://files.pythonhosted.org/packages/3f/7d/714601ab8d790d77d4158af743895fb999216cb02fc6283ab8e54911a887/conformer-0.3.2-py3-none-any.whl
- decorator: BSD-2-Clause. Source: https://files.pythonhosted.org/packages/05/7f/798705f5296a58ca505d600456748d1be48078eac8a7050d8a98bc9edb89/decorator-5.3.1-py3-none-any.whl
- diffusers: Apache 2.0 License. Source: https://files.pythonhosted.org/packages/d5/68/a84d929518c9fbd65febcedd7810203bcac393f9cddd0603ec58df7f93f7/diffusers-0.29.0-py3-none-any.whl
- distlib: PSF-2.0. Source: https://files.pythonhosted.org/packages/02/08/9c41fb51ab5b43eb21674aff13df270e8ba6c4b29c8624e328dc7a9482af/distlib-0.4.3-py2.py3-none-any.whl
- einops: MIT. Source: https://files.pythonhosted.org/packages/2a/09/f8d8f8f31e4483c10a906437b4ce31bdf3d6d417b73fe33f1a8b59e34228/einops-0.8.2-py3-none-any.whl
- fastapi: MIT. Source: https://files.pythonhosted.org/packages/9e/7c/8e3c6ad324ea5cb36604fc3f968554887891c316d9dfde57761611d907ad/fastapi-0.139.0-py3-none-any.whl
- ffmpy: MIT. Source: https://files.pythonhosted.org/packages/55/56/dd3669eccebb6d8ac81e624542ebd53fe6f08e1b8f2f8d50aeb7e3b83f99/ffmpy-1.0.0-py3-none-any.whl
- filelock: MIT. Source: https://files.pythonhosted.org/packages/81/47/dd9a212ef6e343a6857485ffe25bba537304f1913bdbed446a23f7f592e1/filelock-3.29.0-py3-none-any.whl
- fsspec: BSD-3-Clause. Source: https://files.pythonhosted.org/packages/d5/0c/043d5e551459da400957a1395e0febbf771446ff34291afcbe3d8be2a279/fsspec-2026.4.0-py3-none-any.whl
- gradio: Apache-2.0. Source: https://files.pythonhosted.org/packages/38/3c/1568ee82f0e4308612aaf964168e93b7f2adb64c3e77b7877fd397e773bf/gradio-6.8.0-py3-none-any.whl
- gradio_client: Apache-2.0. Source: https://files.pythonhosted.org/packages/c2/49/86b919727b5d6574528d5d9e67c6455bb707a3654abc87d61d7f1d742395/gradio_client-2.2.0-py3-none-any.whl
- groovy: Review package notices. Source: https://files.pythonhosted.org/packages/28/27/3d6dcadc8a3214d8522c1e7f6a19554e33659be44546d44a2f7572ac7d2a/groovy-0.1.2-py3-none-any.whl
- h11: MIT. Source: https://files.pythonhosted.org/packages/04/4b/29cac41a4d98d144bf5f6d33995617b185d14b22401f75ca86f384e87ff1/h11-0.16.0-py3-none-any.whl
- hf-xet: Apache-2.0. Source: https://files.pythonhosted.org/packages/6d/b6/20f99cfe97cc663a711f7b33cc21d4793e51968e9a26125b4afcd77315ba/hf_xet-1.5.1-cp37-abi3-win_amd64.whl
- httpcore: BSD-3-Clause. Source: https://files.pythonhosted.org/packages/7e/f5/f66802a942d491edb555dd61e3a9961140fd64c90bce1eafd741609d334d/httpcore-1.0.9-py3-none-any.whl
- httpx: BSD-3-Clause. Source: https://files.pythonhosted.org/packages/2a/39/e50c7c3a983047577ee07d2a9e53faf5a69493943ec3f6a384bdc792deb2/httpx-0.28.1-py3-none-any.whl
- huggingface_hub: Apache-2.0. Source: https://files.pythonhosted.org/packages/4f/85/b505a99a133d9f99d21af182af416e9baef70bdeef019983479651e494c2/huggingface_hub-1.21.0-py3-none-any.whl
- identify: MIT. Source: https://files.pythonhosted.org/packages/94/84/d9273cd09688070a6523c4aee4663a8538721b2b755c4962aafae0011e72/identify-2.6.19-py2.py3-none-any.whl
- idna: BSD-3-Clause. Source: https://files.pythonhosted.org/packages/1e/5e/d4e9f1a599fb8e573b7b87160658329fbf28d19eac2718f51fc3def3aa5a/idna-3.18-py3-none-any.whl
- importlib_metadata: Apache-2.0. Source: https://files.pythonhosted.org/packages/38/3d/2d244233ac4f76e38533cfcb2991c9eb4c7bf688ae0a036d30725b8faafe/importlib_metadata-9.0.0-py3-none-any.whl
- jaconv: MIT License. Source: https://files.pythonhosted.org/packages/3b/da/9657d637bcacdbaf6a914ce504000da5639f9d945f8d3552a940f021d6c0/jaconv-0.5.0-py3-none-any.whl
- joblib: BSD-3-Clause. Source: https://files.pythonhosted.org/packages/7b/91/984aca2ec129e2757d1e4e3c81c3fcda9d0f85b74670a094cc443d9ee949/joblib-1.5.3-py3-none-any.whl
- lazy-loader: BSD-3-Clause. Source: https://files.pythonhosted.org/packages/8a/a1/8d812e53a5da1687abb10445275d41a8b13adb781bbf7196ddbcf8d88505/lazy_loader-0.5-py3-none-any.whl
- librosa: ISC. Source: https://files.pythonhosted.org/packages/b5/ba/c63c5786dfee4c3417094c4b00966e61e4a63efecee22cb7b4c0387dda83/librosa-0.11.0-py3-none-any.whl
- llvmlite: BSD-2-Clause AND Apache-2.0 WITH LLVM-exception. Source: https://files.pythonhosted.org/packages/aa/f7/b3222b13f2d424dae3c9e63fde476af25ebccf1f3faf0b52d1b79fc15c70/llvmlite-0.48.0-cp311-cp311-win_amd64.whl
- markdown-it-py: Review package notices. Source: https://files.pythonhosted.org/packages/b3/81/4da04ced5a082363ecfa159c010d200ecbd959ae410c10c0264a38cac0f5/markdown_it_py-4.2.0-py3-none-any.whl
- mdurl: Review package notices. Source: https://files.pythonhosted.org/packages/b3/38/89ba8ad64ae25be8de66a6d463314cf1eb366222074cfda9ee839c56a4b4/mdurl-0.1.2-py3-none-any.whl
- ml_dtypes: Apache-2.0. Source: https://files.pythonhosted.org/packages/b4/24/70bd59276883fdd91600ca20040b41efd4902a923283c4d6edcb1de128d2/ml_dtypes-0.5.4-cp311-cp311-win_amd64.whl
- mpmath: BSD. Source: https://files.pythonhosted.org/packages/43/e3/7d92a15f894aa0c9c4b49b8ee9ac9850d6e63b03c9c32c0367a13ae62209/mpmath-1.3.0-py3-none-any.whl
- msgpack: Apache-2.0. Source: https://files.pythonhosted.org/packages/3f/07/ca212739d179f9083bff2c7c08c24101c3555a334fadc2b876b18768a3ae/msgpack-1.2.1-cp311-cp311-win_amd64.whl
- narwhals: MIT. Source: https://files.pythonhosted.org/packages/f4/4e/afc8c31605cb8be1d3bb4438c4d979daa104dab6306cd2b87abe9c3a7299/narwhals-2.23.0-py3-none-any.whl
- networkx: BSD-3-Clause. Source: https://files.pythonhosted.org/packages/9e/c9/b2622292ea83fbb4ec318f5b9ab867d0a28ab43c5717bb85b0a5f6b3b0a4/networkx-3.6.1-py3-none-any.whl
- nodeenv: BSD. Source: https://files.pythonhosted.org/packages/88/b2/d0896bdcdc8d28a7fc5717c305f1a861c26e18c05047949fb371034d98bd/nodeenv-1.10.0-py2.py3-none-any.whl
- numba: BSD. Source: https://files.pythonhosted.org/packages/5e/c9/9476940bc6d5caf5c0cf2e4c5feecbf01244bbe6f914614082dd7a3e520e/numba-0.66.0-cp311-cp311-win_amd64.whl
- numpy: See full package license and bundled third-party notices. Source: https://files.pythonhosted.org/packages/3f/6b/5610004206cf7f8e7ad91c5a85a8c71b2f2f8051a0c0c4d5916b76d6cbb2/numpy-1.26.4-cp311-cp311-win_amd64.whl
- omegaconf: Review package notices. Source: https://files.pythonhosted.org/packages/a4/0e/152509871bf30df6fc38569f52a2db9b55dd41aae957adae50a053ac7778/omegaconf-2.3.1-py3-none-any.whl
- onnx: Apache-2.0. Source: https://files.pythonhosted.org/packages/54/57/cc0a9f2cf4522e42829d089927b4b75924d32f50dca237482e7b741df003/onnx-1.22.0-cp311-cp311-win_amd64.whl
- orjson: MPL-2.0 AND (Apache-2.0 OR MIT). Source: https://files.pythonhosted.org/packages/3f/17/1a1a228183d62d1b77e2c30d210f47dd4768b310ebe1607c63e3c0e3a71e/orjson-3.11.9-cp311-cp311-win_amd64.whl
- packaging: Apache-2.0 OR BSD-2-Clause. Source: https://files.pythonhosted.org/packages/b7/b9/c538f279a4e237a006a2c98387d081e9eb060d203d8ed34467cc0f0b9b53/packaging-26.0-py3-none-any.whl
- pandas: See full package license and bundled third-party notices. Source: https://files.pythonhosted.org/packages/eb/62/c321f13b5ba1819fc8dca456c7fce578da2dcfecff1abbf0eaddf8406c0f/pandas-3.0.3-cp311-cp311-win_amd64.whl
- pillow: MIT-CMU. Source: https://files.pythonhosted.org/packages/69/42/836b6f3cd7f3e5fa10a1f1a5420447c17966044c8fbf589cc0452d5502db/pillow-12.2.0-cp311-cp311-win_amd64.whl
- platformdirs: MIT. Source: https://files.pythonhosted.org/packages/81/e6/cd9575ac904136b3cbf7aa7ee819ef86eedb7274e46f230e94ea4342e729/platformdirs-4.10.0-py3-none-any.whl
- pooch: BSD-3-Clause. Source: https://files.pythonhosted.org/packages/2a/2d/d4bf65e47cea8ff2c794a600c4fd1273a7902f268757c531e0ee9f18aa58/pooch-1.9.0-py3-none-any.whl
- pre_commit: MIT. Source: https://files.pythonhosted.org/packages/80/6e/4b28b62ecb6aae56769c34a8ff1d661473ec1e9519e2d5f8b2c150086b26/pre_commit-4.6.0-py2.py3-none-any.whl
- protobuf: 3-Clause BSD License. Source: https://files.pythonhosted.org/packages/0a/19/8d0cb6f20a1ef7b18f1c8986ad5783f22f84cce39c6ce9a6e645ea55192e/protobuf-7.35.1-cp310-abi3-win_amd64.whl
- pycparser: BSD-3-Clause. Source: https://files.pythonhosted.org/packages/0c/c3/44f3fbbfa403ea2a7c779186dc20772604442dde72947e7d01069cbe98e3/pycparser-3.0-py3-none-any.whl
- pydantic: MIT. Source: https://files.pythonhosted.org/packages/fd/7b/122376b1fd3c62c1ed9dc80c931ace4844b3c55407b6fb2d199377c9736f/pydantic-2.13.4-py3-none-any.whl
- pydantic_core: MIT. Source: https://files.pythonhosted.org/packages/aa/e6/c505f83dfeda9a2e5c995cfd872949e4d05e12f7feb3dca72f633daefa94/pydantic_core-2.46.4-cp311-cp311-win_amd64.whl
- pydub: MIT. Source: https://files.pythonhosted.org/packages/a6/53/d78dc063216e62fc55f6b2eebb447f6a4b0a59f55c8406376f76bf959b08/pydub-0.25.1-py2.py3-none-any.whl
- pykakasi: GPL-3.0-or-later. Source: https://files.pythonhosted.org/packages/0f/e8/11644fe823e05c583b330e9fb81e3e8fc5d079036512a8300fc157be349d/pykakasi-2.3.0-py3-none-any.whl
- pyloudnorm: MIT. Source: https://files.pythonhosted.org/packages/aa/b6/65a49a05614b2548edbba3aab118f2ebe7441dfd778accdcdce9f6567f20/pyloudnorm-0.2.0-py3-none-any.whl
- python-dateutil: Dual License. Source: https://files.pythonhosted.org/packages/ec/57/56b9bcc3c9c6a792fcbaf139543cee77261f3651ca9da0c93f5c1221264b/python_dateutil-2.9.0.post0-py2.py3-none-any.whl
- python-discovery: See full package license and bundled third-party notices. Source: https://files.pythonhosted.org/packages/1a/82/a70006589557f267f15bd384c0642ad49f0d97b690c3a05b166b9dcbad3b/python_discovery-1.4.2-py3-none-any.whl
- python-multipart: Apache-2.0. Source: https://files.pythonhosted.org/packages/e1/04/e8135ebd1ad02c56ec633277529b2602ff99ff634be76cdba5744cf554fd/python_multipart-0.0.32-py3-none-any.whl
- pytz: MIT. Source: https://files.pythonhosted.org/packages/ec/dd/96da98f892250475bdf2328112d7468abdd4acc7b902b6af23f4ed958ea0/pytz-2026.2-py2.py3-none-any.whl
- regex: Apache-2.0 AND CNRI-Python. Source: https://files.pythonhosted.org/packages/c6/cf/a48d8e8d406b22481cad146f48fa0dfca3c5f402b91f26d8e5a0fe4f513d/regex-2026.6.28-cp311-cp311-win_amd64.whl
- requests: Apache-2.0. Source: https://files.pythonhosted.org/packages/a0/f4/c67b0b3f1b9245e8d266f0f112c500d50e5b4e83cb6f3b71b6528104182a/requests-2.34.2-py3-none-any.whl
- resemble-perth: Review package notices. Source: https://files.pythonhosted.org/packages/77/cc/73226dd776f8e9c2975f64f4efc22988fb37e5b185ba5cccd6f2e7196954/resemble_perth-1.0.1-py3-none-any.whl
- rich: MIT. Source: https://files.pythonhosted.org/packages/82/3b/64d4899d73f91ba49a8c18a8ff3f0ea8f1c1d75481760df8c68ef5235bf5/rich-15.0.0-py3-none-any.whl
- s3tokenizer: Apache2.0. Source: https://files.pythonhosted.org/packages/6b/8f/ceddf749baf17405e755643e4d33c7c85bbb609a0c8cf43fc12aaea1c7ab/s3tokenizer-0.3.0-py3-none-any.whl
- safehttpx: Review package notices. Source: https://files.pythonhosted.org/packages/2e/a3/0f0b7d78e2f1eb9e8e1afbff1d2bff8d60144aee17aca51c065b516743dd/safehttpx-0.1.7-py3-none-any.whl
- safetensors: Review package notices. Source: https://files.pythonhosted.org/packages/69/e2/b011c38e5394c4c18fb5500778a55ec43ad6106126e74723ffaee246f56e/safetensors-0.5.3-cp38-abi3-win_amd64.whl
- scikit-learn: BSD-3-Clause. Source: https://files.pythonhosted.org/packages/3b/67/be3d369f40d8178ba3bd86635d132e08cb5329b023e4669d9426d84bc007/scikit_learn-1.9.0-cp311-cp311-win_amd64.whl
- scipy: See full package license and bundled third-party notices. Source: https://files.pythonhosted.org/packages/95/da/0d1df507cf574b3f224ccc3d45244c9a1d732c81dcb26b1e8a766ae271a8/scipy-1.17.1-cp311-cp311-win_amd64.whl
- semantic-version: BSD. Source: https://files.pythonhosted.org/packages/6a/23/8146aad7d88f4fcb3a6218f41a60f6c2d4e3a72de72da1825dc7c8f7877c/semantic_version-2.10.0-py2.py3-none-any.whl
- setuptools: Review package notices. Source: https://files.pythonhosted.org/packages/69/8a/b9dc7678803429e4a3bc9ba462fa3dd9066824d3c607490235c6a796be5a/setuptools-75.8.0-py3-none-any.whl
- shellingham: ISC License. Source: https://files.pythonhosted.org/packages/e0/f9/0595336914c5619e5f28a1fb793285925a8cd4b432c9da0a987836c7f822/shellingham-1.5.4-py2.py3-none-any.whl
- six: MIT. Source: https://files.pythonhosted.org/packages/b7/ce/149a00dd41f10bc29e5921b496af8b574d8413afcd5e30dfa0ed46c2cc5e/six-1.17.0-py2.py3-none-any.whl
- soundfile: BSD 3-Clause License. Source: https://files.pythonhosted.org/packages/ed/97/b39c18ac1df45e755ca22b8b00e872929da5d107998a207a5e4ac831bfda/soundfile-0.14.0-py2.py3-none-win_amd64.whl
- soxr: LGPL-2.1-or-later. Source: https://files.pythonhosted.org/packages/8f/29/371467eb86c7ba6810df0bfe9409bcd9c52ec5615b111190fafe23e4d2e1/soxr-1.1.0-cp311-cp311-win_amd64.whl
- spacy_pkuseg: MIT. Source: https://files.pythonhosted.org/packages/a5/c1/3a5814cdf6600243328ecff4a5a5f3e96086f478dfff88b0f6932023afd7/spacy_pkuseg-1.0.1-cp311-cp311-win_amd64.whl
- srsly: MIT. Source: https://files.pythonhosted.org/packages/d4/a5/6193aa4c08e488821538fcbce2282449e228fd2183ed67d118bb5ccd8b54/srsly-2.5.3-cp311-cp311-win_amd64.whl
- starlette: BSD-3-Clause. Source: https://files.pythonhosted.org/packages/81/0d/13d1d239a25cbfb19e740db83143e95c772a1fe10202dda4b76792b114dd/starlette-0.52.1-py3-none-any.whl
- sympy: BSD. Source: https://files.pythonhosted.org/packages/b2/fe/81695a1aa331a842b582453b605175f419fe8540355886031328089d840a/sympy-1.13.1-py3-none-any.whl
- threadpoolctl: BSD-3-Clause. Source: https://files.pythonhosted.org/packages/32/d5/f9a850d79b0851d1d4ef6456097579a9005b31fea68726a4ae5f2d82ddd9/threadpoolctl-3.6.0-py3-none-any.whl
- tokenizers: Review package notices. Source: https://files.pythonhosted.org/packages/65/71/0670843133a43d43070abeb1949abfdef12a86d490bea9cd9e18e37c5ff7/tokenizers-0.22.2-cp39-abi3-win_amd64.whl
- tomlkit: MIT. Source: https://files.pythonhosted.org/packages/bd/75/8539d011f6be8e29f339c42e633aae3cb73bffa95dd0f9adec09b9c58e85/tomlkit-0.13.3-py3-none-any.whl
- torch: NVIDIA/PyTorch components retain their own notices. Source: https://download-r2.pytorch.org/whl/cu124/torch-2.6.0%2Bcu124-cp311-cp311-win_amd64.whl
- torchaudio: NVIDIA/PyTorch components retain their own notices. Source: https://download-r2.pytorch.org/whl/cu124/torchaudio-2.6.0%2Bcu124-cp311-cp311-win_amd64.whl
- torchvision: NVIDIA/PyTorch components retain their own notices. Source: https://download-r2.pytorch.org/whl/cu124/torchvision-0.21.0%2Bcu124-cp311-cp311-win_amd64.whl
- tqdm: MPL-2.0 AND MIT. Source: https://files.pythonhosted.org/packages/d8/8e/bb97bb0c71802080bfc8952937d174e49cfc50de5c951dd47b2496f0dcdb/tqdm-4.68.3-py3-none-any.whl
- transformers: Apache 2.0 License. Source: https://files.pythonhosted.org/packages/4e/93/79754b0ca486e556c2b95d4f5afc66aaf4b260694f3d6e1b51da2d036691/transformers-5.2.0-py3-none-any.whl
- typer: MIT. Source: https://files.pythonhosted.org/packages/3f/f9/2b3ff4e56e5fa7debfaf9eb135d0da96f3e9a1d5b27222223c7296336e5f/typer-0.25.1-py3-none-any.whl
- typer-slim: MIT. Source: https://files.pythonhosted.org/packages/a7/24/5480c20380dfd18cf33d14784096dca45a24eae6102e91d49a718d3b6855/typer_slim-0.24.0-py3-none-any.whl
- typing-inspection: MIT. Source: https://files.pythonhosted.org/packages/dc/9b/47798a6c91d8bdb567fe2698fe81e0c6b7cb7ef4d13da4114b41d239f65d/typing_inspection-0.4.2-py3-none-any.whl
- typing_extensions: PSF-2.0. Source: https://files.pythonhosted.org/packages/18/67/36e9267722cc04a6b9f15c7f3441c2363321a3ea07da7ae0c0707beb2a9c/typing_extensions-4.15.0-py3-none-any.whl
- tzdata: Apache-2.0. Source: https://files.pythonhosted.org/packages/ce/e4/dccd7f47c4b64213ac01ef921a1337ee6e30e8c6466046018326977efd95/tzdata-2026.2-py2.py3-none-any.whl
- urllib3: MIT. Source: https://files.pythonhosted.org/packages/7f/3e/5db95bcf282c52709639744ca2a8b149baccf648e39c8cc87553df9eae0c/urllib3-2.7.0-py3-none-any.whl
- uvicorn: BSD-3-Clause. Source: https://files.pythonhosted.org/packages/88/fa/e1388bbcf24ef3274f45c0c1c7b501fd14971037c1b6ee23610553307497/uvicorn-0.49.0-py3-none-any.whl
- virtualenv: MIT. Source: https://files.pythonhosted.org/packages/2c/02/3623e6169bed617ed1e2d372f7c69f92ec28d54c4dfc997055c8578ec148/virtualenv-21.5.1-py3-none-any.whl
- wheel: Review package notices. Source: https://files.pythonhosted.org/packages/0b/2c/87f3254fd8ffd29e4c02732eee68a83a1d3c346ae39bc6822dcbcb697f2b/wheel-0.45.1-py3-none-any.whl
- wrapt: BSD-2-Clause. Source: https://files.pythonhosted.org/packages/7e/9c/23695baa331c6de4e874c3d78b8e0bed92e1d2a274e665b29858f6841672/wrapt-2.2.2-cp311-cp311-win_amd64.whl
- zipp: MIT. Source: https://files.pythonhosted.org/packages/3a/13/547360d81e6d88d58492968ffda9f9542854f11310ee556fef14260cc886/zipp-4.1.0-py3-none-any.whl
