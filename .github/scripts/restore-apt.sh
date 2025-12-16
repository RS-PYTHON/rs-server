#!/bin/bash
# Copyright 2023-2025 Airbus, CS Group
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Restore the apt repository list.
# WARNING: works only in Debian/Ubuntu !

# shellcheck source=/dev/null
. /etc/os-release # Source OS release info

if [[ "$ID" == "debian" ]]; then
    cat > /etc/apt/sources.list <<EOF
deb http://deb.debian.org/debian $VERSION_CODENAME main
deb http://security.debian.org/debian-security $VERSION_CODENAME-security main
deb http://deb.debian.org/debian $VERSION_CODENAME-updates main
deb http://deb.debian.org/debian $VERSION_CODENAME-backports main
EOF
elif [[ "$ID" == "ubuntu" ]]; then
    rm -f /etc/apt/sources.list
    for a in "" "-security" "-updates" "-backports"; do
        for b in main multiverse restricted universe; do
            echo "deb http://archive.ubuntu.com/ubuntu ${VERSION_CODENAME}${a} ${b}" >> /etc/apt/sources.list
        done
    done
else
    echo "Unsupported distribution: $ID"
    exit 1
fi

exit 0
