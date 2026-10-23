# Mu-Silicium alioth 设备配置

这些文件是从 Mu-Silicium 工程里改/加出来的 alioth 支持，按下面的路径放回去即可复现这次编出的 UEFI：

| 本目录文件 | 放到 Mu-Silicium 的位置 |
|---|---|
| `alioth.toml` | `Resources/Configs/alioth.toml` |
| `alioth_DeviceBuild.py` | `Platforms/Xiaomi/aliothPkg/DeviceBuild.py` |
| `build_uefi.py` | 工程根目录（覆盖上游脚本；编 UEFI / 生成 boot.img 的入口） |
| `alioth.dts` | `Resources/DTBs/alioth.dtb` 的源码参考（真机导出的 DTS，编成 dtb 后用） |

构建：

```bash
rm -rf Build                     # build_uefi.py 见到 Build/ 就跳过 setup
python3 build_uefi.py -d alioth -r RELEASE
# → Build/aliothPkg/RELEASE_CLANGPDB/FV/SILICIUM_UEFI.fd  (3,145,728 B)
```

FD 基址 `0x9FC00000`、大小 `0x300000`（见 `alioth.toml`），boot.img 由 `build_uefi.py` 的
`create_android_boot_img()` 用 `mkbootimg` 生成（header v1、gzip 内核、附加 DTB）。
本包 `boot/alioth-boot.img` 与 `boot/uefi-alioth.fd` 就是这次构建的产物。
