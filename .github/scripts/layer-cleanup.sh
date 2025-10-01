#!/bin/bash
# Copyright 2024 CS Group
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

apt-get autoclean --yes
apt-get autoremove --yes

rm -rf /var/lib/apt/lists/*
rm -rf /usr/local/src/*

rm -rf /var/cache/apt/*
rm -rf /root/.cache/*
# including /root/.cache/pip
rm -rf /home/*/.cache/*
rm -rf /usr/local/share/.cache/*
# including /usr/local/share/.cache/yarn

rm -rf /tmp/* /var/tmp/*
rm -rf /opt/conda/pkgs/cache

rm -rf /tmp/whl

# WARNING: this removes the apt repository list. To restore it and be able to run 'apt update',
# you must run (works only in Debian):
# . /etc/os-release && echo "deb http://deb.debian.org/debian $VERSION_CODENAME main" > /etc/apt/sources.list
rm -rf /etc/apt/sources.list.d/*

exit 0
