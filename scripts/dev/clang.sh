#!/bin/bash
# Install LLVM 21: clang-format, clang-tidy, lldb.
# Dev images only.
set -euo pipefail

wget https://apt.llvm.org/llvm.sh
chmod +x llvm.sh
./llvm.sh 21
rm llvm.sh

apt-get -y install clang-format-21 clang-tidy-21

ln -sf /usr/bin/clang-21 /usr/local/bin/clang
ln -sf /usr/bin/lldb-21 /usr/local/bin/lldb
ln -sf /usr/bin/clang-format-21 /usr/local/bin/clang-format
ln -sf /usr/bin/clang-tidy-21 /usr/local/bin/clang-tidy

rm -rf /var/lib/apt/lists/*
