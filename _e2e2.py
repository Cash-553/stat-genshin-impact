# -*- coding: utf-8 -*-
"""修完之后，完整走一遍真实更新（真分卷 + 真替换 + 真重启）"""
import io
import os
import shutil
import subprocess
import sys
import time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = r'E:\收益识别'
QT = os.path.join(BASE, 'statgi_qt')
sys.path.insert(0, BASE)
sys.path.insert(0, QT)
os.chdir(QT)

E2E = os.path.join(BASE, '_upd_e2e')
shutil.rmtree(E2E, ignore_errors=True)
APP = os.path.join(E2E, 'StatGI')
os.makedirs(os.path.join(APP, '_internal'), exist_ok=True)
os.makedirs(os.path.join(APP, 'config'), exist_ok=True)
os.makedirs(os.path.join(APP, 'data'), exist_ok=True)

# 假的"旧安装"
open(os.path.join(APP, 'StatGI.exe'), 'w').write('OLD')
open(os.path.join(APP, 'config', 'settings.json'), 'w').write('{"我的设置":"要保住"}')
open(os.path.join(APP, 'data', 'today.json'), 'w').write('{"摩拉":123456}')
print('造好旧安装:', sorted(os.listdir(APP)))

PART_DIR = os.path.join(BASE, '发布版', '公告', '更新包分卷')
parts = sorted(os.listdir(PART_DIR))
p1 = os.path.join(PART_DIR, parts[0])
p2 = os.path.join(PART_DIR, parts[1])
zip_path = os.path.join(BASE, '发布版', 'StatGI_v0.9.zip')
print('分卷:', parts)

import qt_updater
import json
vj = json.load(open(os.path.join(BASE, '发布版', '公告', 'version.json'), encoding='utf-8'))
sha = vj['update']['sha256']

import paths


class P:
    def __init__(self, s):
        self.s = s

    def __truediv__(self, o):
        return P(os.path.join(self.s, o))

    def __fspath__(self):
        return self.s

    def __str__(self):
        return self.s

    def mkdir(self, **kw):
        os.makedirs(self.s, exist_ok=True)

    def exists(self):
        return os.path.exists(self.s)


paths.app_dir = lambda: P(APP)

up = {'size': vj['update']['size'], 'sha256': sha,
      'sources': [{'label': '本地分卷', 'parts': [
          'file:///' + p1.replace('\\', '/'),
          'file:///' + p2.replace('\\', '/')]}]}

print()
print('=== 1) 下载 + 合并 + 校验 + 解压 ===')
t0 = time.time()
newdir = qt_updater.prepare(up, on_log=lambda s: print('   ', s))
print(f'   用时 {time.time()-t0:.1f} 秒')
print('   解压出:', sum(len(f) for _, _, f in os.walk(newdir)), '个文件')

print()
print('=== 2) 生成更新.bat ===')
bat = qt_updater.write_updater(newdir)
print('   ', bat)
raw = open(bat, 'rb').read()
print('   按 GBK 能解码:', end=' ')
try:
    raw.decode('gbk')
    print('✓')
except Exception as e:
    print('✗', e)

print()
print('=== 3) 真的跑一遍更新.bat（模拟用户点了确定之后）===')
print('   （它最后会 start StatGI.exe，那是个假的 3 字节文件，会报"不是有效应用"）')
t0 = time.time()
r = subprocess.run(['cmd', '/c', bat], cwd=APP, stdin=subprocess.DEVNULL,
                   capture_output=True, text=True, encoding='gbk', errors='replace')
out = (r.stdout or '') + (r.stderr or '')
for line in out.splitlines():
    s = line.strip()
    if s and '按任意键' not in s:
        print('   ', s[:100])
print(f'   用时 {time.time()-t0:.1f} 秒，退出码 {r.returncode}')

print()
print('=== 4) 检查替换结果 ===')
print('   StatGI.exe 大小:', os.path.getsize(os.path.join(APP, 'StatGI.exe')),
      '字节（原来 3 字节的假的）')
for k, want in (('config\\settings.json', '要保住'), ('data\\today.json', '123456')):
    p = os.path.join(APP, k)
    if os.path.exists(p):
        c = open(p, encoding='utf-8', errors='replace').read()
        print(f'   {k}: {"✓ 保住了" if want in c else "✗ 被改了"}  {c}')
    else:
        print(f'   {k}: ✗ 没了！！')
n = sum(len(f) for _, _, f in os.walk(APP))
print('   更新后文件数:', n)
print('   _backup 清掉了吗:', not os.path.exists(os.path.join(APP, '_backup')))
print('   data\\_update 清掉了吗:', not os.path.exists(os.path.join(APP, 'data', '_update')))
print('   新版本特有的文件进来了吗:',
      os.path.exists(os.path.join(APP, '_internal', 'python314.dll')))

shutil.rmtree(E2E, ignore_errors=True)
print()
print('清理完成')
