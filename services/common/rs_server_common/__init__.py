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

"""Main package of commons of rs-server services."""

import os

# Set automatically by running `poetry dynamic-versioning`
__version__ = "0.0.0"

# Some kind of workaround for boto3 to avoid checksum being added inside
# the file contents uploaded to the s3 bucket e.g. x-amz-checksum-crc32:xxx
# See: https://github.com/boto/boto3/issues/4435
os.environ["AWS_REQUEST_CHECKSUM_CALCULATION"] = "when_required"
os.environ["AWS_RESPONSE_CHECKSUM_VALIDATION"] = "when_required"
