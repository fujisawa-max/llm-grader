# 今回の実機で確認したllama-server設定

2026-09-09の調査記録。起動済みサーバーの変更は、この文書の作成だけでは行われません。

## 原因

Ricoh（PID 1658）の起動ログには `no usable GPU found, --gpu-layers option will be ignored` があり、CPUで動作していました。前回のリクエストは300秒でキャンセルされ、約352秒後にサーバーが解放されています。

同じ実行ファイルの `--list-devices` は現在 `Vulkan0: Radeon 8060S Graphics` を返し、CMakeCacheもGGML_VULKAN=ONです。再ビルド不足ではなく、起動時点のGPU認識に問題があったと考えられます。起動時の認識失敗の理由は断定していません。ホストの空きメモリは約80GiB、swap使用量0で、調査時点にメモリ逼迫はありませんでした。

Ornith（モデルID ornith）はQ8_0、vision=true、コンテキスト32768、4スロットです。GPU非対応の警告はなく、/proc/10624/fdで /dev/dri/renderD128 を開いていることも確認しました。Ricohのプロセスにはこのデバイスのオープンはありませんでした。

## 変更案

Ricohは現在GPUを認識できる状態で再起動する必要があります。次の変更を含めたsystemd drop-inを `config/systemd/llama-qwen3vl-ricoh.override.conf` に用意しました。

| 設定 | 現在 | 変更案・理由 |
|---|---|---|
| GPU | `-ngl 999` のみ | `--device Vulkan0 -ngl 999`。指定GPUが見つからなければ起動エラーとなり、CPUで静かに動き続けることを防ぐ |
| 並列数 | 既定の4 | `--parallel 1`。今回の逐次実行に合わせる |
| コンテキスト | `-c 8192` | `-c 16384`。前回の入力4234トークンと出力上限4096の合計は8192を少し超えるため余裕を持たせる |
| 論理・物理バッチ | `-b 2048 -ub 512` | まず維持。タイムアウトの第一の対処はGPUの有効化 |
| Flash Attention | `-fa on` | 維持 |

Ornithの `-c 32768 -b 4096 -ub 1024 -fa auto` はまず維持できます。こちらも将来の再起動時に `--device Vulkan0 --parallel 1` を追加すると今回の運用に合います。並列数4が今回のCPU動作の原因だったという意味ではありません。

画像の上限トークン数を下げると細かな数式やグラフの認識に影響し得るため、速度を測る前には変更しません。ランナーがtemperature=0を送るため、サーバー既定のtemperature変更も不要です。

## 設定の適用と確認

以下はサービス変更と再起動を伴います。作業フォルダ内の設定案を確認してから、リポジトリルートで実行してください。既に同名drop-inがある場合は上書き前に内容を確認してください。

```bash
sudo install -d /etc/systemd/system/llama-qwen3vl-ricoh.service.d
sudo install -m 644 config/systemd/llama-qwen3vl-ricoh.override.conf /etc/systemd/system/llama-qwen3vl-ricoh.service.d/scoring.conf
sudo systemctl daemon-reload
sudo systemctl restart llama-qwen3vl-ricoh.service
journalctl -u llama-qwen3vl-ricoh.service -n 60 --no-pager
.venv/bin/python -m scoring check
```

取り消しは追加した `scoring.conf` のみを外し、daemon-reloadとサービス再起動を行います。元のunitファイルは変更しません。

再起動後、GPU非認識の警告が消え、モデルのGPU offloadが行われていることをログまたはGPUデバイスのオープン状態で確認してからOCRを再試行します。`/props` のvision=trueは画像入力機能の確認であって、GPU利用の証明ではありません。

参照: [llama.cpp公式ビルド説明](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#vulkan)。CLI引数は実際に使用している `/home/fujisawa/llama.cpp-qwen38next/tools/server/README.md` と `common/arg.cpp` を確認しました。

## 利用者による修正後の確認

2026-09-09 07:51 UTCに、Ricohの再起動後の設定を確認しました。

- `--device Vulkan0 --parallel 1 -c 16384 -b 4096 -ub 1024 -fa on`
- `/props`: Q8_0、vision=true、total_slots=1、コンテキスト16384
- GPU非認識警告は消え、実答案リクエストでトークン生成が開始されたことを確認

利用者が指定したバッチ値4096/1024でまず動作を確認します。再試行の保存先は `runs/BasicMathSmallExam1-gpu-pilot/` です。
