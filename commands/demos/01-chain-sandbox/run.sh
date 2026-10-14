#!/usr/bin/env bash
# Демо 1: setup + chain из 5 задач.
set -e
cd "$(dirname "$0")/../../.."   # корень ai-coder

bash commands/demos/01-chain-sandbox/setup.sh

ai-coder agent /tmp/chain-test \
    --chain issues/demos/01-chain-sandbox/ \
    --tool-loop --apply \
    --stop-on-fail \
    --max-cost-rub 3
