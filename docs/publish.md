# PyPI への公開手順

`llm-ai-api` を PyPI に公開する手順です。

## 0. 事前準備（初回のみ）

1. [PyPI](https://pypi.org/account/register/) にアカウントを作り、2FA（二要素認証）を有効にする。
2. 公開用ツールを入れる。

   ```sh
   python3 -m pip install --upgrade build twine
   ```

3. API トークンを作る。
   - PyPI の Account settings → API tokens → Add API token。
   - 初回は、プロジェクトがまだ存在しないため **Scope: Entire account** で作る。
   - 2 回目以降は、`llm-ai-api` 限定のトークンを作り直し、全アカウント用のトークンは削除する。
   - トークン（`pypi-...`）は一度しか表示されない。安全な場所に保管し、リポジトリには絶対に置かない。
4. トークンを `~/.pypirc` に保存する（またはアップロード時に入力する）。

   ```ini
   [pypi]
   username = __token__
   password = pypi-xxxxxxxx
   ```

   ```sh
   chmod 600 ~/.pypirc
   ```

   環境変数で渡す場合は `TWINE_USERNAME=__token__` と `TWINE_PASSWORD=pypi-...` を使う。

## 1. バージョンを決める

バージョンは次の **2 か所** にあり、必ず同じ値にする。

- `pyproject.toml` の `version`
- `src/llm_ai_api/__init__.py` の `__version__`

**PyPI は、一度アップロードしたバージョンの再アップロードを許可しない（削除しても同じ番号は使えない）。** 失敗したら、番号を上げて出し直す。

## 2. 公開前の確認

```sh
# テスト（実装後）
python3 -m unittest discover -s tests

# 古いビルド成果物を消す
rm -rf dist build src/*.egg-info

# ビルド
python3 -m build

# メタデータと README の検証
python3 -m twine check dist/*
```

確認すること:

- `dist/` に `.whl` と `.tar.gz` が 1 つずつできている。ファイル名のバージョンが意図したものと一致している。
- `twine check` が両方 `PASSED`。
- 依存が `httpx` だけになっている（`unzip -p dist/*.whl '*/METADATA' | grep Requires-Dist`）。
- `README.md` を英語版にしている（PyPI のページに表示される）。

## 3. TestPyPI で試す（推奨）

本番に出す前に、[TestPyPI](https://test.pypi.org/)（別アカウント・別トークンが必要）で確認できる。

```sh
python3 -m twine upload --repository testpypi dist/*

# 別の仮想環境にインストールして確認
python3 -m venv /tmp/llm-ai-api-test
/tmp/llm-ai-api-test/bin/pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  llm-ai-api
/tmp/llm-ai-api-test/bin/python -c "import llm_ai_api; print(llm_ai_api.__version__)"
```

`--extra-index-url` は、依存の `httpx` を本番 PyPI から取るために必要。

## 4. 本番にアップロードする

```sh
python3 -m twine upload dist/*
```

アップロード後に確認する。

- https://pypi.org/project/llm-ai-api/ が表示され、README とバージョンが正しい。
- 新しい仮想環境でインストールして動く。

  ```sh
  python3 -m venv /tmp/llm-ai-api-check
  /tmp/llm-ai-api-check/bin/pip install llm-ai-api
  /tmp/llm-ai-api-check/bin/python -c "import llm_ai_api; print(llm_ai_api.__version__)"
  ```

反映が遅れることがあるため、インストールに失敗したら数分待ってから再試行する。

## 5. 公開後の作業

1. git にタグを打つ。

   ```sh
   git tag v0.0.1
   git push origin v0.0.1
   ```

2. 初回のみ: アカウント全体のトークンを削除し、`llm-ai-api` 限定のトークンに切り替える。

## 公開してはいけないもの

- API キー（OpenAI / OpenRouter / Anthropic）やトークン。`dist/` の中身に混ざっていないか、`tar tzf dist/*.tar.gz` で確認する。
- 公開は取り消せない。PyPI の「yank」は新規インストールを避けさせるだけで、ファイルは残る。迷ったら TestPyPI で先に試す。

## 将来: GitHub Actions による自動公開（任意）

PyPI の [Trusted Publisher](https://docs.pypi.org/trusted-publishers/) を設定すると、トークンなしで GitHub Actions から公開できる。

1. PyPI のプロジェクト設定 → Publishing → GitHub のリポジトリとワークフロー名を登録する。
2. タグ（`v*`）の push で `python -m build` → `pypa/gh-action-pypi-publish` を実行するワークフローを作る。

GitHub リポジトリが決まってから設定する。
