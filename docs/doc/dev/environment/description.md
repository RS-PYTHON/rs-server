The following table describes the development technical stack and
explains briefly the choices that have been made.

<table>
<colgroup>
<col style="width: 33%" />
<col style="width: 33%" />
<col style="width: 33%" />
</colgroup>
<thead>
<tr class="header">
<th>Need</th>
<th>Chosen techno</th>
<th>Rational elements</th>
</tr>
</thead>
<tbody>
<tr class="odd">
<td><p>language</p></td>
<td><p>python</p></td>
<td><p>the language commonly used by the final users</p></td>
</tr>
<tr class="even">
<td><p>language version</p></td>
<td><p>python 3.11</p></td>
<td><p>python 3.12 is too recent to be chosen</p></td>
</tr>
<tr class="odd">
<td><p>dependency management</p></td>
<td><p>poetry</p></td>
<td><p>easy to use, good dependency management</p></td>
</tr>
<tr class="even">
<td><p>code formatting</p></td>
<td><p>black</p></td>
<td><p>the current standard</p></td>
</tr>
<tr class="odd">
<td><p>unittests</p></td>
<td><p>pytest</p></td>
<td><p>standard</p></td>
</tr>
<tr class="even">
<td><p>lint</p></td>
<td><p>pylint, flake8</p></td>
<td><p>standard</p></td>
</tr>
<tr class="odd">
<td><p>type check</p></td>
<td><p>mypy</p></td>
<td><p>commonly used by the team</p></td>
</tr>
<tr class="even">
<td><p>quality check</p></td>
<td><p>sonarqube</p></td>
<td><p>commonly used by the team</p></td>
</tr>
<tr class="odd">
<td><p>commit check</p></td>
<td><p>pre-commit</p></td>
<td><p>commonly used by the team</p></td>
</tr>
<tr class="even">
<td><p>security check</p></td>
<td><p>trivy</p></td>
<td><p>used in the previous phase</p></td>
</tr>
<tr class="odd">
<td><p>technical documentation</p></td>
<td><p>asciidoctor</p></td>
<td><p>good standard, simple syntax, good feedback from a team member</p></td>
</tr>
</tbody>
</table>
