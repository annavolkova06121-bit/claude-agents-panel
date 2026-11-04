# Пресеты вступления и плюхи

Четыре стиля одной механики: плёнка стекает в начале ролика, в конце из центра прилетает плюха и закрывает кадр. Тайминги, оверлеи 1080x1920 и звуковые дорожки у всех одинаковые по структуре, поэтому стили взаимозаменяемы.

| Стиль | Папка | Флаг `--preset` | Звук |
|---|---|---|---|
| Токсичный | `acid_slime_loop` | `acid` | кислота и шипение |
| Лава | `lava_loop` | `lava` | гул, густые блопы, пар, треск, тяжёлый удар |
| Лава объёмная | `lava_real_loop` | `lavar` | как у лавы |
| Море | `sea_loop` | `sea` | вода, пузыри, капли, всплеск |

```bash
python presets/acid_slime_loop/tools/apply_preset.py in.mp4 out.mp4 --preset lava
python presets/acid_slime_loop/tools/apply_preset.py --check --preset sea
```

Подробности по установке, громкости и ducking: `acid_slime_loop/README.md` (общий инструмент `apply_preset.py` лежит там же).

Пересборка «Лавы», «Лавы объёмной» и «Моря» из исходников: `python presets/_source/build_theme_preset.py lava|lavar|sea`
(анимация: `_source/overlay_themed.html`, звук: `tools/sfx_themes.py`; усиления выравниваются по громкости с «Токсичным»).
