# H.3-C.1 Teacher Review Package

この文書はread-onlyです。Teacher Review前のDraft/evidenceを提示し、承認・Correction・Confirm・Approveは実行していません。

17問: CLEAN_FOR_ACCEPT候補 10問、review_required 7問、明示criteria 48件。
Student data access: 0。Teacher Reviewフェーズのmodel calls: 0。

## Overall summary

| Sample | Drafts | Review required | Current max-points guard |
|---|---:|---:|---|
| sampleQ1 | 6 | 0 | authoritative values |
| sampleQ2 | 4 | 4 | Q2: all UNSET |
| sampleQ3 | 3 | 0 | authoritative values |
| sampleQ4 | 4 | 3 | authoritative values |

## Priority decisions

### Q1 H.3-D candidate

Question ID: `8a2a7955-2347-4c67-8581-f800721ec558`
Stable key: `review-48e6195a-5d0-q3.1`
max_points: 10.0

ModelAnswer Draft:

教師付き学習とは、入力データと正解を示すラベルの組を用いて、未知の入力に対する答えを
予測できるよう学習する方法である。予測と正解の誤差が小さくなるようモデルを調整し、画
像の分類や数値の予測などに利用される。

Rubric Draft:
- `sampleQ1-3.1-criterion-1`: 5点, `EXPLICIT_SOURCE` — Source criterion; teacher review required for exact wording.
- `sampleQ1-3.1-criterion-2`: 5点, `EXPLICIT_SOURCE` — Source criterion; teacher review required for exact wording.

Teacher decision: `ACCEPT / EDIT / REJECT`

### Q2 score reconciliation

| Question ID | Label | Current max_points | Source criterion points | Decision |
|---|---|---|---|---|
| `24a42587-a730-408c-8565-1221cba11453` | (1) | UNSET | [None, 10] | APPLY / EDIT / KEEP_UNSET |
| `dbd8a6e7-8fdd-475c-adb7-652db377ab8a` | (2) | UNSET | [None, 10] | APPLY / EDIT / KEEP_UNSET |
| `5928d0e3-ea16-48e4-b9ff-a96209e4eb37` | 問題2 | UNSET | [None, 10] | APPLY / EDIT / KEEP_UNSET |
| `8c8c578c-1635-4f13-91e8-4b40dbe3e258` | 問題３ | UNSET | [5, 10] | APPLY / EDIT / KEEP_UNSET |

Q2の `5点ないし10点` は自動確定していません。

### Q4 Problem 3 point conflict

Question ID: `4c567426-da7a-4aae-bccc-a0026b69f219`
Authoritative max_points: 40.0
Source criteria points: `[15, 15, 5, 5, 5, 5]`
Source criterion total: `50.0`
Difference: `+10.0`

Source evidence:

でできていれば10 点 
➢ 途中までの場合部分点5 点 
⚫ 平方完成ができていれば10 点 
➢ 途中までの場合部分点5 点 
⚫ 放物線の向きがあっていれば5 点 
⚫ 頂点の座標が書けていれば5 点 
⚫ x 軸との交点が書けていれば5 点 
⚫ y 軸との交点が書けていれば5 点 
途中式15 点 
正答15 点

Teacher decision required: custom edit / accept source interpretation / reject

### Q4 reference assets

| Owner | Role | Asset ID | Bbox | SHA-256 |
|---|---|---|---|---|
| `705f1d12-4f19-4c33-b197-39212f24b3ca` | model_answer_reference_figure | `6163634f-fa79-52e1-b33f-673c32d8bc74` | `[0.51, 0.46, 0.9, 0.61]` | `fd1c3e7ba0197b37955b9e4364b7b1b7722e87d1c4bc2abcd1c3fdf50fc70023` |
| `4c567426-da7a-4aae-bccc-a0026b69f219` | model_answer_reference_figure | `2fda5c6e-ba46-5077-8694-5c1266d1fa7a` | `[0.08, 0.715, 0.42, 0.855]` | `3df8046ae0345de287a0062a294f6b2c7bbf4da1cfa6f30926084591271e9644` |

## Other question details

### sampleQ1

| Question ID | Label | max_points | Context | Context SHA | Review | Warnings |
|---|---|---:|---|---|---|---|
| `3d5d8e20-46b7-42c2-96bd-3e7aeb62963b` | (1) | 20.0 | READY | `e5d986c04795cf8a37306f21c0760788062f4f0e8c6bd50c8e10b50cfc01916a` | CLEAN_FOR_ACCEPT | NONE |
| `9a3ba4aa-8e79-4dda-b15a-807f4364d6c3` | (2) | 20.0 | READY | `f88796d526451a69f23947286b51cc0f3a9dc5dc15d5721cc8046b61b1df5e6a` | CLEAN_FOR_ACCEPT | NONE |
| `a8f32cd9-1d3d-4242-9ef6-3b45fecb5f74` | 問題2 | 30.0 | READY | `5c763e64fc5e2fb6923cb96d179a239d594634ab9f58afba2d4f8b52273132ed` | CLEAN_FOR_ACCEPT | NONE |
| `8a2a7955-2347-4c67-8581-f800721ec558` | (1) | 10.0 | READY | `87a0f63103b8159a8e395f5077efdcc6c1d8db84b063f2d7a0663c74c021f8bf` | CLEAN_FOR_ACCEPT | NONE |
| `b759cd39-630f-4be6-8d59-85ddefb61293` | (2) | 10.0 | READY | `0a48b3d637aeb2bd8cffaf99c45d5a8d863d6356f9b7b61eab833a85805f40fa` | CLEAN_FOR_ACCEPT | NONE |
| `6a1543bc-13ea-4ea1-a02a-6669ff147f83` | (3) | 10.0 | READY | `8793ef3c9bcdc031c3dcae6f261e74e94dad856b3cfd05fc34604223f2885cff` | CLEAN_FOR_ACCEPT | NONE |

### sampleQ2

| Question ID | Label | max_points | Context | Context SHA | Review | Warnings |
|---|---|---:|---|---|---|---|
| `24a42587-a730-408c-8565-1221cba11453` | (1) | UNSET | READY | `fc0231ffb17c062acc97164f42c391dad7f3b9d4c870b60bc848731d8ee1ed78` | REVIEW_REQUIRED | AMBIGUOUS_SOURCE_SCORE |
| `dbd8a6e7-8fdd-475c-adb7-652db377ab8a` | (2) | UNSET | READY | `5ecde0a0fea414bcb0046669a7a47595178b618936e0995f9c54dbc1d2fc55b3` | REVIEW_REQUIRED | AMBIGUOUS_SOURCE_SCORE |
| `5928d0e3-ea16-48e4-b9ff-a96209e4eb37` | 問題2 | UNSET | READY | `7b34c29792907f6ae67dd74a9845176cc0d0d59916a2e2bcd7ab7c9bd0a5576e` | REVIEW_REQUIRED | MISSING_AUTHORITATIVE_MAX_POINTS |
| `8c8c578c-1635-4f13-91e8-4b40dbe3e258` | 問題３ | UNSET | READY | `e9eaf3ecc515cf8a190782f42dfc50236b7c9ba17dc18166c667f1eed90f59fb` | REVIEW_REQUIRED | AMBIGUOUS_SOURCE_SCORE |

### sampleQ3

| Question ID | Label | max_points | Context | Context SHA | Review | Warnings |
|---|---|---:|---|---|---|---|
| `ad991321-ce7b-4f67-a4a3-1f23b89e29e2` | 問題1 | 30.0 | READY | `62a7c655d9ffff29a80a7336da4e034cf61fc657cb81ec085e5d908f5cc8e853` | CLEAN_FOR_ACCEPT | NONE |
| `7b81a7ce-e028-4e9c-ba51-e57e4913ffae` | 問題2 | 30.0 | READY | `6dfb6bcbbae54446b5a7910bfc652e6ceae0d5e66aebaf35ce563c3e940ceb29` | CLEAN_FOR_ACCEPT | NONE |
| `7fcbd8ee-1eee-4d93-a195-59ea995a0385` | 問題3 | 40.0 | READY | `ee342244c42e99871937816a8e598abe075e03fbe027ce1fce2d42ddc277f974` | CLEAN_FOR_ACCEPT | NONE |

### sampleQ4

| Question ID | Label | max_points | Context | Context SHA | Review | Warnings |
|---|---|---:|---|---|---|---|
| `ab3e65c7-7dca-4254-a4d9-757ebf675f28` | 問題1 | 30.0 | READY | `d22fa7635708ea157356f1b2aa23519b425c0dc9301441432a483c3cdde40805` | REVIEW_REQUIRED | RUBRIC_TOTAL_MISMATCH |
| `02669a76-cb99-4ea1-bfd4-c742ff1617a3` | (1) | 20.0 | READY | `ade40813e9cd8cc49633431fd5d0115dc6492cacfd990ce4111781bae2c7f897` | REVIEW_REQUIRED | RUBRIC_TOTAL_MISMATCH |
| `705f1d12-4f19-4c33-b197-39212f24b3ca` | (2) | 20.0 | READY | `d82fb622a874d1c8be0405237f96589384823253c0dcea7b5dda13097237fe41` | CLEAN_FOR_ACCEPT | NONE |
| `4c567426-da7a-4aae-bccc-a0026b69f219` | 問題3 | 40.0 | READY | `351bf4a111f267b36d647ea69fe3303a7b2b34651a6a1584979250f1c4381cbc` | REVIEW_REQUIRED | RUBRIC_TOTAL_MISMATCH |

## Response template

Q1 clean: `ACCEPT_ALL / individual edits`

Q1 H.3-D candidate ModelAnswer: `ACCEPT / EDIT / REJECT`

Q1 H.3-D candidate Rubric: `ACCEPT / EDIT / REJECT`

Q2 score reconciliation: `APPLY / EDIT / KEEP_UNSET` per question

Q2 ambiguous criteria: teacher wording/points

Q3 clean: `ACCEPT_ALL / edits`

Q4 clean: `ACCEPT_ALL / edits`

Q4 Problem 3 conflict: teacher decision

Q4 reference images: `ACCEPT / RE-CROP`

**Teacher responseがあるまで、ModelAnswer Confirm / Rubric Approve / Question Correctionを実行しません。**
