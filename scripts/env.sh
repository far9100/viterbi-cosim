# 由 setup_eda.sh 產生。所有 script 開頭 source 這一支。
export OSS_CAD="/home/far/opt/oss-cad-suite"
export PATH="$OSS_CAD/bin:$PATH"
export PATH="$HOME/fec-cosim/.venv/bin:$PATH"   # 必須在 oss-cad-suite 之後，才能蓋掉它自帶的 python
