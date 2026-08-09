#!/usr/bin/env python3
# 修复存档 CT-01 误替换：CT-01 的「她」实际指 Clementine（不在 CT-01 角色集），
# 脚本误用唯一女性候选 Maeve。此处把 CT-01 块内误替换的 Maeve 改回 Clementine，
# 保护真实 Maeve 位置（Maeve在楼梯口 / Maeve Millay 关联角色）。
import re, glob, os, sys

def fix_ct01(path):
    with open(path, encoding='utf-8') as f:
        text = f.read()
    m = re.search(r'(^CT-01:.*?)(?=^CT-02:)', text, re.M | re.S)
    if not m:
        print(f"{path}: 未找到 CT-01 块，跳过")
        return
    block = m.group(1)
    protected = []
    def protect(mo):
        protected.append(mo.group(0))
        return f'\u00a7P{len(protected)-1}\u00a7'
    block2 = re.sub(r'Maeve在[^\s，。·、；！？]*|Maeve Millay', protect, block)
    block2 = block2.replace('Maeve', 'Clementine')
    for i, p in enumerate(protected):
        block2 = block2.replace(f'\u00a7P{i}\u00a7', p)
    if block2 == block:
        print(f"{path}: CT-01 无变化")
        return
    text = text[:m.start(1)] + block2 + text[m.end(1):]
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f"{path}: CT-01 已修复（误替换 Maeve→Clementine，保护 {len(protected)} 处真实 Maeve）")

if __name__ == '__main__':
    snaps = sys.argv[1] if len(sys.argv) > 1 else 'worlds/westworld/snaps'
    for p in sorted(glob.glob(os.path.join(snaps, '*', 'conflicts.yaml'))):
        fix_ct01(p)
