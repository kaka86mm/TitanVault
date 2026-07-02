# mineru-rocm 镜像第三方许可说明

> 本文件标注 `images/mineru-rocm/Dockerfile.rocm` 构建的镜像所引入的、**需要用户知悉**的第三方许可。
> 本文件自包含于镜像目录, 因为这些许可是该镜像特有的合规义务。

## MinerU (opendatalab/MinerU)

- 用途: PDF 解析主框架 (`mineru[core]==3.4.0`, `magic-pdf==1.3.12`)
- 许可: **MinerU Open Source License** (基于 Apache-2.0, 附 MAU / 收入门槛等附加条件)
  - 上游: https://github.com/opendatalab/MinerU/blob/master/LICENSE.md
- ⚠️ **AGPL-3.0 传染链**: MinerU 的 PDF 解析依赖 **PyMuPDF (AGPL-3.0)** 与部分 **YOLO 权重 (AGPL-3.0)**。
  - 若你二次分发本镜像或基于其修改, AGPL-3.0 的 copyleft 义务可能触发 (开源你的修改)。
  - 参考: https://github.com/opendatalab/MinerU/issues/2122

## FunASR (modelscope/FunASR) — 仅 sensevoice 镜像, 此处供交叉参考

- 用途: ASR 推理框架 (Apache-2.0)
- ⚠️ **模型许可与框架不同**: `SenseVoiceSmall` / VAD 模型走 **FunASR Model Open Source License v1.1** (Alibaba 自定义, 含商用门槛), 运行时从 modelscope/hf 拉取, 不打进镜像。
  - 上游: https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE

## doclayout-yolo

- 用途: 文档版面检测 (`doclayout-yolo==0.0.2b1`)
- 许可: AGPL-3.0 (YOLO 系列权重)

## 用户义务

- 个人/内部使用: 上述许可均允许。
- 商用/二次分发: 务必阅读 MinerU 许可的附加条件, 并评估 PyMuPDF/YOLO 的 AGPL-3.0 影响。
