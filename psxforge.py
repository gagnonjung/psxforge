"""
PSX 롬 폴더 정리 스크립트
--------------------------
원본 폴더는 절대 수정하지 않습니다.
모든 결과는 <루트>/output/ 폴더에 생성됩니다.

실행 순서:
  [1] output/ 초기화 (기존 output 삭제 후 재생성)
  [2] 원본 폴더 스캔 및 그룹화
      - 지역 약어 정규화 (K) -> (Korea)
      - 멀티 디스크 그룹 (Disc 1)/(Disc 2) -> (2 Discs)
      - 레거시 폴더명 (2 Discs) Game -> Game (2 Discs)
  [3] output/ 에 복사
      - bin 병합(필요시)은 트랙 수와 무관하게 항상 수행
      - 멀티 트랙(CDDA 오디오 포함)인 경우만 cu2 시트 추가 생성
      - 싱글 트랙(대부분의 일반 게임)은 cue/cu2 불필요, bin만 있으면 충분
        (PSIO는 *.BIN/*.ISO/*.IMG 이미지만 직접 읽음)
  [4] MULTIDISC.LST 생성 (각 게임 하위 폴더 안에, 항상 이미지(.bin) 파일명 기준)
  [5] 썸네일 다운로드 (output/ 각 폴더에)

사용법:
  python psxforge.py                # 현재 폴더 대상
  python psxforge.py /path/to/dir   # 특정 폴더 대상
"""

import os
import re
import sys
import shutil
import urllib.request
from collections import defaultdict

# ════════════════════════════════════════════════
# 패턴 / 상수
# ════════════════════════════════════════════════

DISC_PATTERN = re.compile(
    r'[\(\[]?\s*(?:discs?|dics?|disk|cd)\s*(\d+)\s*[\)\]]?',
    flags=re.IGNORECASE
)

REGION_PATTERN = re.compile(
    r'(\((?:Japan|USA|Europe|Korea|World|Asia|Brazil|France|Germany|Italy|Spain'
    r'|Australia|China|Taiwan|Sweden|Netherlands|Russia|Canada|Latin America)[^)]*\))',
    flags=re.IGNORECASE
)

LEGACY_PREFIX_PATTERN = re.compile(
    r'^\((\d+)\s*Discs?\)\s+',
    flags=re.IGNORECASE
)

REGION_ABBR_MAP = {
    'J': 'Japan', 'JPN': 'Japan',
    'U': 'USA', 'US': 'USA',
    'E': 'Europe', 'EU': 'Europe', 'EUR': 'Europe',
    'K': 'Korea', 'KR': 'Korea', 'KOR': 'Korea',
    'W': 'World',
    'A': 'Asia', 'AS': 'Asia',
    'B': 'Brazil', 'BR': 'Brazil',
    'F': 'France', 'FR': 'France',
    'G': 'Germany', 'DE': 'Germany',
    'I': 'Italy', 'IT': 'Italy',
    'S': 'Spain', 'ES': 'Spain',
    'AU': 'Australia', 'AUS': 'Australia',
    'C': 'Canada', 'CA': 'Canada',
    'CN': 'China', 'CHN': 'China',
    'TW': 'Taiwan', 'TWN': 'Taiwan',
    'SW': 'Sweden', 'SWE': 'Sweden',
    'NL': 'Netherlands',
    'RU': 'Russia', 'RUS': 'Russia',
}

REGION_ABBR_PATTERN = re.compile(
    r'\((' + '|'.join(sorted(REGION_ABBR_MAP.keys(), key=len, reverse=True)) + r')\)',
    flags=re.IGNORECASE
)

# cu2 관련
SECTORS_PER_SECOND = 75
SECONDS_PER_MINUTE = 60
BLOCK_SIZES = {
    'MODE1/2048': 2048, 'MODE1/2352': 2352,
    'MODE2/2336': 2336, 'MODE2/2352': 2352,
    'AUDIO': 2352,
}

# 썸네일
SERIAL_REGEX = re.compile(
    r'((SLPS|SLES|SLUS|SCPS|SCUS|SCES|SIPS|SLPM|SLEH|SLED|SCED|ESPM|PBPX|LSP)[_P\-])|(LSP9|907127)'
)
SERIAL_EXCEPTIONS = {'SLUSP': 'SLUS_', 'LSP9': 'LSP_9', '907127': 'LSP_907127'}
COVER_URL = "https://ncirocco.github.io/PSIO-Library/images/covers_by_id/{}.bmp"
BUFFER_SIZE = 1024 * 1024

# 진단용: bin/cue가 없어서 스캔 단계에서 통째로 건너뛴 원본 폴더 이름 모음
SKIPPED_NO_GAME_FILES: list[str] = []


# ════════════════════════════════════════════════
# 이름 정규화 유틸
# ════════════════════════════════════════════════

def expand_region_abbr(name: str) -> str:
    """(K) -> (Korea) 등 약어를 풀네임으로 치환."""
    def replacer(m):
        full = REGION_ABBR_MAP.get(m.group(1).upper())
        return f"({full})" if full else m.group(0)
    return REGION_ABBR_PATTERN.sub(replacer, name)


def fix_legacy_prefix(name: str) -> str:
    """(2 Discs) Game (Japan) -> Game (2 Discs) (Japan)"""
    m = LEGACY_PREFIX_PATTERN.match(name)
    if not m:
        return name
    disc_count = int(m.group(1))
    remainder = name[m.end():]
    return make_dest_name(remainder, disc_count)


def make_dest_name(base_name: str, disc_count: int) -> str:
    """Game (Japan) + 2 -> Game (2 Discs) (Japan)"""
    disc_tag = f"({disc_count} Discs)"
    m = REGION_PATTERN.search(base_name)
    if m:
        pos = m.start()
        return (base_name[:pos].rstrip() + ' ' + disc_tag + ' ' + base_name[pos:]).strip()
    return f"{base_name} {disc_tag}"


def normalize_folder_name(name: str) -> str:
    """약어 확장 -> 레거시 접두사 수정을 순서대로 적용."""
    name = expand_region_abbr(name)
    name = fix_legacy_prefix(name)
    return name


def strip_disc(name: str):
    """이름에서 디스크 번호 제거 -> (기본이름, 번호)."""
    m = DISC_PATTERN.search(name)
    if not m:
        return None, None
    base = DISC_PATTERN.sub('', name).strip()
    base = re.sub(r'\s{2,}', ' ', base).strip(' -_')
    return base, int(m.group(1))


# ════════════════════════════════════════════════
# [2] 원본 스캔 및 그룹화
# ════════════════════════════════════════════════

def has_game_files(path: str) -> bool:
    """폴더에 bin 또는 cue 파일이 하나라도 있는지 확인."""
    for fname in os.listdir(path):
        if fname.lower().endswith(('.bin', '.cue')):
            return True
    return False


def scan_source(parent: str) -> list[tuple[str, list[str]]]:
    """
    원본 폴더를 스캔해서 (출력폴더명, [원본폴더경로, ...]) 리스트를 반환.
    - bin/cue 없는 빈 폴더는 스킵
    - 멀티 디스크 폴더는 하나의 그룹으로 묶임
    - 단일 폴더는 그대로
    - 폴더명은 normalize_folder_name 으로 정규화
    """
    # 1단계: 모든 하위 폴더 수집 (빈 폴더 제외)
    entries = []
    for entry in os.listdir(parent):
        full_path = os.path.join(parent, entry)
        if not os.path.isdir(full_path) or entry == 'output':
            continue
        if not has_game_files(full_path):
            print(f"  ⏭ bin/cue 없음, 건너뜀: {entry}")
            SKIPPED_NO_GAME_FILES.append(entry)
            continue
        entries.append(entry)

    # 2단계: 멀티 디스크 그룹화 (정규화 이름 기준)
    disc_groups: dict[str, list[tuple[str, int]]] = defaultdict(list)
    singles = []

    for entry in entries:
        norm = normalize_folder_name(entry)
        base, disc_num = strip_disc(norm)
        if base is not None:
            disc_groups[base].append((entry, disc_num))
        else:
            singles.append(entry)

    # 3단계: 결과 조합
    result = []

    # 멀티 디스크 그룹
    for base_name, folder_list in disc_groups.items():
        if len(folder_list) == 1:
            # 디스크 번호 태그는 있지만 쌍이 없는 경우 → 단독 처리
            singles.append(folder_list[0][0])
            continue
        sorted_list = sorted(folder_list, key=lambda x: x[1])
        max_disc = max(n for _, n in sorted_list)
        dest_name = make_dest_name(expand_region_abbr(base_name), max_disc)
        src_paths = [os.path.join(parent, f) for f, _ in sorted_list]
        result.append((dest_name, src_paths))

    # 단독 폴더
    for entry in singles:
        dest_name = normalize_folder_name(entry)
        result.append((dest_name, [os.path.join(parent, entry)]))

    return sorted(result, key=lambda x: x[0])


# ════════════════════════════════════════════════
# CUE 파싱 / cu2 변환 유틸
# ════════════════════════════════════════════════

def parse_cue(cue_path: str):
    """cue 파싱 -> (bin_files, tracks)"""
    bin_files, tracks = [], []
    try:
        with open(cue_path, 'r', encoding='utf-8-sig', errors='replace') as f:
            for line in f:
                fields = line.strip().split()
                if not fields:
                    continue
                key = fields[0].upper()
                if key == 'FILE':
                    m = re.search(r'FILE\s+"([^"]+)"', line, re.IGNORECASE)
                    if not m:
                        m = re.search(r"FILE\s+'([^']+)'", line, re.IGNORECASE)
                    fname = m.group(1) if m else ' '.join(fields[1:-1])
                    bin_files.append(fname)
                elif key == 'TRACK':
                    tracks.append({'id': int(fields[1]), 'type': fields[2], 'indexes': []})
                elif key == 'INDEX' and tracks:
                    tracks[-1]['indexes'].append({'id': int(fields[1]), 'stamp': fields[2]})
    except Exception:
        pass
    return bin_files, tracks


def stamp_to_sectors(stamp: str) -> int:
    mm, ss, ff = (int(x) for x in stamp.strip().split(':'))
    return mm * SECONDS_PER_MINUTE * SECTORS_PER_SECOND + ss * SECTORS_PER_SECOND + ff


def sectors_to_stamp(sectors: int) -> str:
    mm = sectors // (SECTORS_PER_SECOND * SECONDS_PER_MINUTE)
    rem = sectors % (SECTORS_PER_SECOND * SECONDS_PER_MINUTE)
    ss = rem // SECTORS_PER_SECOND
    ff = sectors % SECTORS_PER_SECOND
    return f"{mm:02d}:{ss:02d}:{ff:02d}"


def generate_cu2(cue_path: str, bin_path: str) -> str:
    """cu2 문자열 생성 (github.com/ncirocco/cue-to-cu2 동일 로직)."""
    _, tracks = parse_cue(cue_path)
    if not tracks:
        raise ValueError(f"TRACK 없음: {cue_path}")

    block_size = BLOCK_SIZES.get(tracks[0]['type'].upper(), 2352)
    total_sectors = os.path.getsize(bin_path) // block_size
    size_stamp = sectors_to_stamp(total_sectors)

    lines = [
        f"ntracks {len(tracks)}\r\n",
        f"size {size_stamp}\r\n",
        "data1 00:02:00\r\n",
    ]

    for track in tracks:
        tid, idxs = track['id'], track['indexes']
        if tid == 1:
            continue
        if len(idxs) == 1:
            s = stamp_to_sectors(idxs[0]['stamp'])
            stamp = sectors_to_stamp(s + 2 * SECTORS_PER_SECOND)
            lines.append(f"pregap{tid:02d} {stamp}\r\n")
            lines.append(f"track{tid:02d} {stamp}\r\n")
        else:
            pregap = next((i['stamp'] for i in idxs if i['id'] == 0), idxs[0]['stamp'])
            base = next((i['stamp'] for i in idxs if i['id'] == 1), idxs[-1]['stamp'])
            s = stamp_to_sectors(base)
            lines.append(f"pregap{tid:02d} {pregap}\r\n")
            lines.append(f"track{tid:02d} {sectors_to_stamp(s + 2 * SECTORS_PER_SECOND)}\r\n")

    end = stamp_to_sectors(size_stamp) + 2 * SECTORS_PER_SECOND
    lines.append(f"\r\ntrk end {sectors_to_stamp(end)}")
    return ''.join(lines)


def merge_bins(cue_path: str, output_bin_path: str):
    """멀티 bin을 순서대로 병합."""
    cue_dir = os.path.dirname(cue_path)
    bin_files, _ = parse_cue(cue_path)
    with open(output_bin_path, 'wb') as out:
        for bf in bin_files:
            src = os.path.join(cue_dir, bf)
            if not os.path.exists(src):
                raise FileNotFoundError(f"bin 없음: {src}")
            with open(src, 'rb') as inp:
                shutil.copyfileobj(inp, out)


def write_merged_cue(cue_path: str, output_dir: str, new_bin_name: str):
    """단일 bin 참조 cue 생성."""
    with open(cue_path, 'r', encoding='utf-8-sig', errors='replace') as f:
        lines = f.readlines()

    new_lines, written = [], False
    for line in lines:
        if re.match(r'\s*FILE\s+', line, re.IGNORECASE):
            if not written:
                new_lines.append(f'FILE "{new_bin_name}" BINARY\r\n')
                written = True
        else:
            new_lines.append(line)

    with open(os.path.join(output_dir, os.path.basename(cue_path)), 'w', encoding='utf-8') as f:
        f.writelines(new_lines)


# ════════════════════════════════════════════════
# [3] output/ 에 복사
# ════════════════════════════════════════════════

def copy_non_bin_cue_files(src_folder: str, dest_dir: str):
    """bin/cue 제외한 파일(bmp 등)을 dest_dir 로 복사."""
    for fname in os.listdir(src_folder):
        fpath = os.path.join(src_folder, fname)
        if not os.path.isfile(fpath):
            continue
        if os.path.splitext(fname)[1].lower() in ('.bin', '.cue'):
            continue
        dst = os.path.join(dest_dir, fname)
        if not os.path.exists(dst):
            shutil.copy2(fpath, dst)


def _list_disc_units(src: str) -> list:
    """
    한 원본 폴더(src) 안에 디스크가 몇 개 들어있는지 판단해서,
    디스크별 대표 cue 파일명 목록을 반환한다 (cue가 없으면 [None]).

    - cue가 2개 이상 있으면: 폴더 하나에 여러 디스크가 합쳐져 있는 경우
      (예: "Xenogears (Japan) (2 Discs)/disc1.cue, disc2.cue")
      → cue 파일명 리스트를 그대로 반환 (디스크별로 1개씩)
    - cue가 1개면: 평범한 단일 디스크 폴더 → [그 cue 파일명]
    - cue가 없으면: bin 유무에 따라 [None] (bin 기반 처리는 호출부에서 처리)
    """
    cues = sorted(f for f in os.listdir(src) if f.lower().endswith('.cue'))
    if cues:
        return cues
    return [None]


def process_group(dest_name: str, src_paths: list, output_base: str):
    """
    (dest_name, src_paths) 하나를 처리해서 output_base/dest_name/ 에 저장.
    - src_paths가 1개이고 그 폴더 안에 cue/bin이 디스크 1세트뿐이면: 싱글 디스크 → 그대로 처리
    - 그 외(= 디스크가 2개 이상으로 판단되는 모든 경우):
        · src_paths가 여러 개 (폴더가 Disc 1/ Disc 2 처럼 분리된 경우), 또는
        · src_paths가 1개지만 그 폴더 안에 cue가 2개 이상 들어있는 경우
          (예: "Game (2 Discs)/disc1.cue, disc2.cue" 처럼 한 폴더에 모여있는 경우)
      → 각 디스크를 독립적으로 처리해서 대표 폴더에 모으고 MULTIDISC.LST 생성

    반환: 'merged' | 'copied' | 'skipped'
    """
    dest_dir = os.path.join(output_base, dest_name)
    os.makedirs(dest_dir, exist_ok=True)

    # ── 디스크 단위 목록 구성 ───────────────────────────────
    # (소스 폴더 경로, 그 폴더 안에서 사용할 cue 파일명 또는 None) 의 리스트.
    # - 폴더가 디스크별로 분리되어 있으면: src_paths 길이만큼 항목이 생김
    # - 폴더 하나에 cue가 여러 개 모여 있으면: 그 폴더 하나에서 여러 항목이 생김
    disc_units = []
    for src in src_paths:
        for cue_name in _list_disc_units(src):
            disc_units.append((src, cue_name))

    is_multi_disc = len(disc_units) >= 2

    # ── 싱글 디스크 (디스크 1개로 확정된 경우) ───────────────────────────
    if not is_multi_disc:
        src = src_paths[0]
        all_cues = sorted(f for f in os.listdir(src) if f.lower().endswith('.cue'))

        if not all_cues:
            for fname in os.listdir(src):
                fpath = os.path.join(src, fname)
                if os.path.isfile(fpath):
                    shutil.copy2(fpath, os.path.join(dest_dir, fname))
            return 'copied'

        cue_path = os.path.join(src, all_cues[0])
        bin_files, tracks = parse_cue(cue_path)
        cue_stem = os.path.splitext(all_cues[0])[0]
        merged_bin_name = cue_stem + '.bin'
        merged_bin_path = os.path.join(dest_dir, merged_bin_name)

        # bin 병합(필요시)은 트랙 수와 무관하게 항상 수행한다.
        if len(bin_files) <= 1:
            src_bin = os.path.join(src, bin_files[0]) if bin_files else None
            if src_bin and os.path.exists(src_bin):
                shutil.copy2(src_bin, merged_bin_path)
            else:
                raise FileNotFoundError(f"bin 파일 없음: {src}")
        else:
            merge_bins(cue_path, merged_bin_path)

        if len(tracks) >= 2:
            # 멀티 트랙(CDDA 오디오 포함) → PSIO가 cu2 시트를 요구함
            write_merged_cue(cue_path, dest_dir, merged_bin_name)
            cu2_content = generate_cu2(os.path.join(dest_dir, cue_stem + '.cue'), merged_bin_path)
            with open(os.path.join(dest_dir, cue_stem + '.cu2'), 'w', encoding='utf-8') as f:
                f.write(cu2_content)
        # 싱글 트랙(대부분의 일반 게임) → PSIO는 *.BIN/*.ISO/*.IMG 만 읽으므로
        # cue/cu2 가 전혀 필요 없다. bin 하나만 있으면 충분.

        copy_non_bin_cue_files(src, dest_dir)
        return 'merged'

    # ── 멀티 디스크 (디스크 2개 이상으로 확정된 경우) ──────────────────
    disc_names = []  # MULTIDISC.LST 에 적힐 "디스크당 대표 파일명" 목록
    # 같은 src 폴더에서 이미 복사한 "cue/bin 외 파일"은 중복 복사하지 않도록 추적
    copied_extra_srcs = set()

    for disc_index, (src, cue_name) in enumerate(disc_units, start=1):
        if cue_name is None:
            # cue 없으면 bin(또는 그 외 파일)을 그대로 복사하고,
            # 대표 bin 파일명을 디스크 목록에 기록한다.
            copied_bin_name = None
            for fname in sorted(os.listdir(src)):
                fpath = os.path.join(src, fname)
                if not os.path.isfile(fpath):
                    continue
                new_fname = expand_region_abbr(fname)
                dst_path = os.path.join(dest_dir, new_fname)
                # 디스크별 파일명이 겹치면(예: 둘 다 "game.bin") Disc N 접두사를 붙여 구분
                if os.path.exists(dst_path):
                    stem, ext = os.path.splitext(new_fname)
                    new_fname = f"{stem} (Disc {disc_index}){ext}"
                    dst_path = os.path.join(dest_dir, new_fname)
                shutil.copy2(fpath, dst_path)
                if copied_bin_name is None and new_fname.lower().endswith('.bin'):
                    copied_bin_name = new_fname
            if copied_bin_name:
                disc_names.append(copied_bin_name)
            copied_extra_srcs.add(src)
            continue

        cue_path = os.path.join(src, cue_name)
        bin_files, tracks = parse_cue(cue_path)
        cue_stem = os.path.splitext(cue_name)[0]

        # 같은 dest_dir 안에서 cue stem이 겹치면(여러 디스크가 같은 "game.cue"를 쓰는 경우,
        # 또는 한 폴더 안의 여러 cue가 우연히 같은 stem을 갖는 경우)
        # Disc N 접미사를 붙여 구분한다.
        final_stem = cue_stem
        if any(n.startswith(cue_stem + '.') for n in disc_names) or \
           os.path.exists(os.path.join(dest_dir, cue_stem + '.cue')):
            final_stem = f"{cue_stem} (Disc {disc_index})"

        # bin 병합(필요시)은 트랙 수와 무관하게 항상 수행한다.
        merged_bin_name = final_stem + '.bin'
        merged_bin_path = os.path.join(dest_dir, merged_bin_name)

        if len(bin_files) <= 1:
            src_bin = os.path.join(src, bin_files[0]) if bin_files else None
            if src_bin and os.path.exists(src_bin):
                shutil.copy2(src_bin, merged_bin_path)
            else:
                raise FileNotFoundError(f"bin 파일 없음: {src}")
        else:
            merge_bins(cue_path, merged_bin_path)

        if len(tracks) >= 2:
            # 멀티 트랙(CDDA 오디오 포함) → PSIO가 cu2 시트를 요구함
            # (cu2는 bin과 같은 이름으로 같은 폴더에 있으면 PSIO가 자동으로 찾아 짝지음)
            write_merged_cue(cue_path, dest_dir, merged_bin_name)
            generated_cue_path = os.path.join(dest_dir, os.path.basename(cue_path))
            final_cue_path = os.path.join(dest_dir, final_stem + '.cue')
            if generated_cue_path != final_cue_path:
                os.replace(generated_cue_path, final_cue_path)

            cu2_content = generate_cu2(final_cue_path, merged_bin_path)
            with open(os.path.join(dest_dir, final_stem + '.cu2'), 'w', encoding='utf-8') as f:
                f.write(cu2_content)
        # 싱글 트랙(대부분의 일반 게임) → cue/cu2 불필요, bin만 있으면 됨

        # PSIO는 *.BIN 이미지를 직접 읽으므로 MULTIDISC.LST 에는 항상 bin 파일명을 적는다
        # (cu2가 있어도 그건 같은 이름의 보조 시트일 뿐, LST 항목은 이미지 파일 기준)
        disc_names.append(merged_bin_name)

        # bmp 등 나머지 파일 복사 (폴더당 한 번만 — 폴더에 디스크가 여러 개 있어도 중복 복사 방지)
        if src not in copied_extra_srcs:
            copy_non_bin_cue_files(src, dest_dir)
            copied_extra_srcs.add(src)

    # MULTIDISC.LST 생성 (cue가 있든 없든, 디스크 수만큼 채워졌으면 생성)
    if len(disc_names) >= 2:
        lst_path = os.path.join(dest_dir, 'MULTIDISC.LST')
        with open(lst_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(disc_names) + '\n')

    return 'merged'


def repair_missing_cu2(dest_dir: str, src_paths: list) -> int:
    """
    이미 처리되어 output/ 에 존재하는 게임 폴더의 cu2 상태를 보정한다.
    트랙 수 판단은 원본 폴더(src_paths)의 cue를 파싱해서 수행한다.

    원본 폴더별로 cue를 찾아:
      - 멀티 트랙(CDDA) 디스크이고 output에 cu2가 없으면 → cu2 생성
      - 싱글 트랙 디스크이고 output에 cu2가 있으면 → 잘못 만들어진 cu2 삭제

    output의 cue/cue.bak 에는 의존하지 않는다.
    bin 파일은 삭제하거나 수정하지 않는다.

    반환: 변경된 항목 개수.
    """
    count = 0

    for src in src_paths:
        src_cues = sorted(f for f in os.listdir(src) if f.lower().endswith('.cue'))
        if not src_cues:
            continue

        for cue_name in src_cues:
            src_cue_path = os.path.join(src, cue_name)
            _, tracks = parse_cue(src_cue_path)
            if not tracks:
                continue

            cue_stem = os.path.splitext(cue_name)[0]
            # dest_dir 안에 같은 stem 의 bin/cu2 가 있는지 확인
            # (파일명 충돌 방지로 stem 이 변경된 케이스도 있으므로 두 가지 다 시도)
            for stem in (cue_stem, cue_stem):
                out_bin  = os.path.join(dest_dir, stem + '.bin')
                out_cu2  = os.path.join(dest_dir, stem + '.cu2')
                out_cue  = os.path.join(dest_dir, stem + '.cue')

                if not os.path.isfile(out_bin):
                    continue

                if len(tracks) >= 2:
                    # 멀티 트랙: cu2 없으면 생성 (cue도 같이 필요)
                    if not os.path.isfile(out_cu2):
                        if not os.path.isfile(out_cue):
                            # cue 가 없으면 원본에서 다시 써서 임시 사용 후 생성
                            write_merged_cue(src_cue_path, dest_dir, stem + '.bin')
                        try:
                            cu2_content = generate_cu2(out_cue, out_bin)
                        except Exception:
                            continue
                        with open(out_cu2, 'w', encoding='utf-8') as f:
                            f.write(cu2_content)
                        count += 1
                else:
                    # 싱글 트랙: cu2 있으면 삭제
                    if os.path.isfile(out_cu2):
                        os.remove(out_cu2)
                        count += 1
                break  # bin 을 찾았으면 다음 cue 로

    return count


def repair_missing_multidisc_lst(dest_dir: str) -> bool:
    """
    output/ 에 존재하는 멀티디스크 게임 폴더의 MULTIDISC.LST를 점검하고,
    필요하면 새로 만들거나 덮어쓴다.

    다음 두 가지 경우를 모두 처리한다:
      1) MULTIDISC.LST가 아예 없는 경우 → 새로 생성
      2) MULTIDISC.LST는 있지만 내용이 "낡은" 경우 → 덮어쓰기
         (예: cu2로 다시 처리되었는데 LST에는 옛날 .cue 항목이 그대로
          남아있어서 PSIO가 디스크 파일을 못 찾는 경우)

    cue/bin/cu2 파일 자체는 수정하거나 삭제하지 않는다 (LST 텍스트만 손댐).
    디스크가 2개 미만으로 판단되면 아무것도 하지 않고 False를 반환한다.
    """
    lst_path = os.path.join(dest_dir, 'MULTIDISC.LST')

    bins = sorted(f for f in os.listdir(dest_dir) if f.lower().endswith('.bin'))
    isos = sorted(f for f in os.listdir(dest_dir) if f.lower().endswith(('.iso', '.img')))
    cues = sorted(f for f in os.listdir(dest_dir) if f.lower().endswith('.cue'))

    # PSIO는 *.BIN/*.ISO/*.IMG 이미지를 직접 읽는다. cu2는 그 옆에 있는
    # CDDA 보조 시트일 뿐이므로 MULTIDISC.LST 에는 이미지 파일명을 적어야 한다.
    # bin이 있으면 bin을 우선 사용, 없으면 iso/img, 그것도 없으면(이상 케이스) cue.
    if len(bins) >= 2:
        disc_entries = bins
    elif len(isos) >= 2:
        disc_entries = isos
    else:
        disc_entries = cues

    if len(disc_entries) < 2:
        return False  # 멀티디스크로 볼 근거 부족 (싱글 디스크 게임일 가능성)

    if os.path.isfile(lst_path):
        with open(lst_path, 'r', encoding='utf-8', errors='replace') as f:
            existing_lines = [ln.strip() for ln in f if ln.strip()]

        # 이미 있는 LST가 지금 폴더 상태와 정확히 일치하면 손대지 않는다
        if existing_lines == disc_entries:
            return False

        # bin/iso 이미지가 있는데 LST 내용이 그것과 정확히 일치하지 않으면
        # (옛날 .cue 항목이 남아있든, 잘못 만들어진 .cu2 항목이 적혀있든) 낡은 것으로 보고 덮어씀.
        # bin/iso가 전혀 없어서 cue 기준으로 적힌 경우만 정상적인 기존 상태로 보고 그대로 둔다.
        is_stale = bool(bins or isos)
        if not is_stale:
            return False

    with open(lst_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(disc_entries) + '\n')
    return True


# ════════════════════════════════════════════════
# [5] 썸네일 다운로드
# ════════════════════════════════════════════════

def get_psx_serial(bin_path: str) -> str | None:
    """bin 파일에서 PSX 시리얼 추출 (github.com/ncirocco/psx-serial-number 동일 로직)."""
    SERIAL_CODE_DOT = 8
    SERIAL_CODE_LEN = 11
    try:
        with open(bin_path, 'rb') as f:
            while True:
                chunk = f.read(BUFFER_SIZE)
                if not chunk:
                    break
                text = chunk.decode('latin-1', errors='replace')
                m = SERIAL_REGEX.search(text)
                if m:
                    raw = text[m.start():m.start() + SERIAL_CODE_LEN]
                    s = raw.replace('.', '').replace('-', '_', 1).replace('-', '')
                    for key, val in SERIAL_EXCEPTIONS.items():
                        if key in s:
                            s = s.replace(key, val)
                    return s[:SERIAL_CODE_DOT] + '.' + s[SERIAL_CODE_DOT:SERIAL_CODE_LEN - 1]
    except Exception:
        pass
    return None


def download_thumbnails(output_base: str):
    ok, fail, skip = [], [], []

    for entry in sorted(os.listdir(output_base)):
        folder = os.path.join(output_base, entry)
        if not os.path.isdir(folder):
            continue

        if any(f.lower().endswith('.bmp') for f in os.listdir(folder)):
            skip.append(entry)
            continue

        bins = sorted(f for f in os.listdir(folder) if f.lower().endswith('.bin'))
        if not bins:
            fail.append((entry, "bin 없음"))
            continue

        serial = get_psx_serial(os.path.join(folder, bins[0]))
        if not serial:
            fail.append((entry, "시리얼 인식 불가"))
            continue

        dest_bmp = os.path.join(folder, f"{serial}.bmp")
        print(f"  다운로드: {entry} ({serial})")
        try:
            urllib.request.urlretrieve(COVER_URL.format(serial), dest_bmp)
            ok.append((entry, serial))
            print(f"    ✅ {serial}.bmp")
        except Exception:
            fail.append((entry, f"커버 없음 ({serial})"))
            print(f"    ⚠ 커버 없음: {serial}")
            if os.path.exists(dest_bmp):
                os.remove(dest_bmp)

    print(f"\n  결과: 다운로드 {len(ok)}개 / 스킵(이미 있음) {len(skip)}개 / 실패 {len(fail)}개")
    for entry, reason in fail:
        print(f"    ✗ {entry}: {reason}")


# ════════════════════════════════════════════════
# 메인
# ════════════════════════════════════════════════

def main():
    root = sys.argv[1] if len(sys.argv) > 1 else '.'
    root = os.path.abspath(root)

    if not os.path.isdir(root):
        print(f"오류: 폴더를 찾을 수 없습니다 -> {root}")
        sys.exit(1)

    output_base = os.path.join(root, 'output')

    print(f"루트 폴더: {root}")
    print("=" * 60)

    # [1] output 폴더 준비 (삭제 없이 유지)
    os.makedirs(output_base, exist_ok=True)
    print(f"\n[1] output 폴더: {output_base}")

    # [2] 원본 스캔 및 그룹화
    print("\n[2] 원본 스캔 및 그룹화")
    groups = scan_source(root)
    multi = [(d, s) for d, s in groups if len(s) >= 2]
    single = [(d, s) for d, s in groups if len(s) == 1]
    print(f"  총 {len(groups)}개 폴더 (멀티 디스크 그룹 {len(multi)}개, 단독 {len(single)}개)")
    for dest_name, src_paths in multi:
        print(f"    📀 {dest_name}")
        for src in src_paths:
            print(f"       <- {os.path.basename(src)}")
    if single:
        print(f"  단독 폴더 {len(single)}개:")
        for dest_name, src_paths in single:
            print(f"    📄 {dest_name}  <- {os.path.basename(src_paths[0])}")
    if SKIPPED_NO_GAME_FILES:
        print(f"  ⏭ bin/cue 없어서 통째로 건너뛴 폴더 {len(SKIPPED_NO_GAME_FILES)}개:")
        for name in SKIPPED_NO_GAME_FILES:
            print(f"    - {name}")

    # [3] output 에 복사 (이미 있는 폴더는 스킵)
    print("\n[3] output/ 에 복사 및 변환")
    merged_count = copied_count = skipped_count = error_count = repaired_count = cu2_repaired_count = 0

    for dest_name, src_paths in groups:
        dest_dir = os.path.join(output_base, dest_name)

        if os.path.isdir(dest_dir):
            # 폴더가 있어도 비어있으면 다시 처리
            if any(os.listdir(dest_dir)):
                did_something = False

                # (1) 원본 cue 기준으로 싱글/멀티 트랙 판단 후 cu2 보정
                #     싱글 트랙 → 잘못 만들어진 cu2 삭제
                #     멀티 트랙 → cu2 누락 시 생성
                n_cu2_fixed = repair_missing_cu2(dest_dir, src_paths)
                if n_cu2_fixed:
                    print(f"  🩹 cu2 보정 ({n_cu2_fixed}건): {dest_name}")
                    cu2_repaired_count += n_cu2_fixed
                    did_something = True

                # (2) 멀티 디스크 게임인데 MULTIDISC.LST 만 빠져 있으면 그것만 보충 생성
                # (다른 파일들은 일절 건드리지 않음)
                # 판단은 repair_missing_multidisc_lst 가 dest_dir 안의 실제 cu2/cue/bin 개수로 함
                # (원본이 Disc 1/2로 분리된 폴더든, 한 폴더에 cue가 여러 개 모인 경우든 모두 커버)
                if repair_missing_multidisc_lst(dest_dir):
                    print(f"  🩹 MULTIDISC.LST 보충/갱신: {dest_name}")
                    repaired_count += 1
                    did_something = True

                if not did_something:
                    print(f"  ⏭ 이미 존재, 건너뜀: {dest_name}")
                    skipped_count += 1
                continue
            else:
                print(f"  🔄 빈 폴더 재처리: {dest_name}")
                os.rmdir(dest_dir)

        print(f"  처리 중: {dest_name}")
        try:
            result = process_group(dest_name, src_paths, output_base)
        except Exception as e:
            print(f"    ⚠ 오류: {e}")
            error_count += 1
            continue

        if result == 'merged':
            print(f"    ✅ bin 병합(필요시) + cu2 생성")
            merged_count += 1
        else:
            print(f"    📋 그대로 복사")
            copied_count += 1

    print(f"\n  결과: cu2 생성 {merged_count}개 / 복사 {copied_count}개 "
          f"/ 기존 {skipped_count}개 / LST 보충 {repaired_count}개 "
          f"/ cu2 보충 {cu2_repaired_count}개 / 오류 {error_count}개")

    # [4] MULTIDISC.LST 확인 (각 게임 폴더 안에 생성됨, output 루트에는 만들지 않음)
    print("\n[4] MULTIDISC.LST 확인")
    multi_dest_names = []
    for dest_name, _src_paths in groups:
        d = os.path.join(output_base, dest_name)
        if not os.path.isdir(d):
            continue
        n_cu2 = sum(1 for f in os.listdir(d) if f.lower().endswith('.cu2'))
        n_cue = sum(1 for f in os.listdir(d) if f.lower().endswith('.cue'))
        n_bin = sum(1 for f in os.listdir(d) if f.lower().endswith('.bin'))
        if max(n_cu2, n_cue, n_bin) >= 2:
            multi_dest_names.append(dest_name)

    if multi_dest_names:
        for dest_name in multi_dest_names:
            lst_path = os.path.join(output_base, dest_name, 'MULTIDISC.LST')
            mark = "✅" if os.path.isfile(lst_path) else "✗ 없음"
            print(f"  {mark}  {dest_name}/MULTIDISC.LST")
    else:
        print("  멀티 디스크 없음, 생성 안 함.")

    # [5] 썸네일 다운로드
    print("\n[5] 썸네일 다운로드")
    download_thumbnails(output_base)

    print("\n" + "=" * 60)
    print(f"완료! 결과물: {output_base}")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print("\n" + "=" * 60)
        print(f"❌ 처리 중 오류가 발생했습니다: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n" + "=" * 60)
        input("종료하려면 Enter 키를 누르세요...")
