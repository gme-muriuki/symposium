#!/bin/sh
set -eu

cache_dir="${1:-/cache}"
version="$2"
cache_file="$3"
expected_size="$4"
expected_hash="$5"
platform="linux-x64"
url="https://downloads.claude.ai/claude-code-releases/$version/$platform/claude"
part_count=8
chunk_size=$(( (expected_size + part_count - 1) / part_count ))
target="$cache_dir/$cache_file"

download_part() {
    index="$1"
    start=$((index * chunk_size))
    end=$((start + chunk_size - 1))
    if [ "$end" -ge "$expected_size" ]; then
        end=$((expected_size - 1))
    fi

    part="$cache_dir/$cache_file.part.$index"
    expected_part_size=$((end - start + 1))
    existing_size=0
    if [ -f "$part" ]; then
        existing_size="$(wc -c < "$part")"
    fi
    if [ "$existing_size" -gt "$expected_part_size" ]; then
        printf 'part %s is too large: %s\n' "$index" "$existing_size" >&2
        return 1
    fi
    if [ "$existing_size" -eq "$expected_part_size" ]; then
        return 0
    fi

    resume_start=$((start + existing_size))
    curl \
        --fail \
        --silent \
        --show-error \
        --location \
        --connect-timeout 60 \
        --retry 10 \
        --retry-all-errors \
        --retry-delay 2 \
        --range "$resume_start-$end" \
        "$url" >> "$part"

    actual_part_size="$(wc -c < "$part")"
    if [ "$actual_part_size" -ne "$expected_part_size" ]; then
        printf 'part %s size mismatch: %s\n' "$index" "$actual_part_size" >&2
        return 1
    fi
}

mkdir -p "$cache_dir"
pids=""
index=0
while [ "$index" -lt "$part_count" ]; do
    download_part "$index" &
    pids="$pids $!"
    index=$((index + 1))
done

failed=0
for pid in $pids; do
    wait "$pid" || failed=1
done
if [ "$failed" -ne 0 ]; then
    printf 'one or more range downloads failed; partial files were retained\n' >&2
    exit 1
fi

assembled="$target.parallel"
: > "$assembled"
index=0
while [ "$index" -lt "$part_count" ]; do
    cat "$cache_dir/$cache_file.part.$index" >> "$assembled"
    index=$((index + 1))
done

actual_size="$(wc -c < "$assembled")"
if [ "$actual_size" -ne "$expected_size" ]; then
    printf 'assembled size mismatch: %s\n' "$actual_size" >&2
    exit 1
fi

actual_hash="$(sha256sum "$assembled" | cut -d ' ' -f 1)"
if [ "$actual_hash" != "$expected_hash" ]; then
    printf 'checksum mismatch: %s\n' "$actual_hash" >&2
    exit 1
fi

mv "$assembled" "$target"
rm -f "$cache_dir/$cache_file".part.*
printf 'cached claude-code %s %s bytes=%s\n' "$version" "$platform" "$actual_size"
