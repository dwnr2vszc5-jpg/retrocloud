# RetroCloud

GPU gerektirmeyen, self-hosted bir retro cloud gaming sistemi. Oyun sunucuda CPU ile çalışır (RetroArch + Mesa llvmpipe), görüntü x264 ile kodlanır ve WebRTC ile tarayıcıya gider. Her oyuncunun kendi oyun süreci, ekranı, ses kanalı ve girdisi vardır.

**Durum: Phase 0 tamam (yerelde).** Tek oyunculu yayın ve iki bağımsız oturum, sandbox bir Linux makinesinde ve sertleştirilmiş Docker konteynerinde uçtan uca test edildi. Bulut deploy'u henüz yapılmadı.

| Belge | İçerik |
|---|---|
| [docs/feasibility.md](docs/feasibility.md) | Riskler, gerçek test sonuçları, teknoloji karşılaştırması (Sunshine, Wolf, Selkies, Neko...), neden XTEST |
| [docs/cost-analysis.md](docs/cost-analysis.md) | GCP ve Azure fiyatları, ücretsiz krediler, senaryolar, maliyet güvenliği |
| [docs/architecture.md](docs/architecture.md) | Mermaid mimari ve akış diyagramları, yığın gerekçeleri, güvenlik, SaaS tasarımı |
| [docs/benchmark-phase0.md](docs/benchmark-phase0.md) | CPU, FPS, bitrate, gecikme ölçümleri |
| [docs/deployment.md](docs/deployment.md) | GCP'ye adım adım deploy, start/stop, destroy |
| [docs/roadmap.md](docs/roadmap.md) | Phase 1-5 planı, lisans notları |

## Yerelde çalıştırma (Ubuntu 24.04)

```bash
sudo apt-get install -y --no-install-recommends retroarch libretro-nestopia libgl1-mesa-dri xvfb pulseaudio \
  gstreamer1.0-tools gstreamer1.0-plugins-{base,good,bad,ugly} gstreamer1.0-x gstreamer1.0-pulseaudio \
  gstreamer1.0-nice gir1.2-gst-plugins-bad-1.0 gir1.2-gst-plugins-base-1.0 python3-gi python3-aiohttp python3-xlib
/usr/bin/python3 -m pip install --break-system-packages -r game-worker/requirements-dev.txt

cd game-worker
RC_DEV=1 RC_WORKER_TOKEN=yerel-gelistirme-tokeni RC_DATA_DIR=/tmp/rcdata /usr/bin/python3 -m worker.app
# http://127.0.0.1:8080 → token'ı girin → "Başlat"
```

Docker ile:

```bash
docker build -t retrocloud/game-worker:dev game-worker
docker run --rm --network host --read-only --tmpfs /tmp:mode=1777 --cap-drop ALL \
  --security-opt no-new-privileges -e RC_WORKER_TOKEN=yerel-gelistirme-tokeni retrocloud/game-worker:dev
```

Kontroller: ok tuşları, X = A, Z = B, S = X, A = Y, Q/W = L/R, Enter = Start, Sağ Shift = Select. Gamepad API ile her standart kumanda çalışır. Dokunmatik ekranda ekran üstü tuşlar çıkar. Not: tarayıcılar Gamepad API'yi sadece HTTPS'te (veya localhost'ta) açar.

TestPad: D-pad kareyi hareket ettirir, A ton çalar, B arka plan rengini değiştirir, Select kayan arka planı açar/kapatır, Start kareyi ortalar.

## Mac'te çalıştırma (ev ağı, bulut ücreti yok)

```bash
scripts/run_local_mac.sh          # Docker Desktop gerekir; adresi yazar (http://<mac-ip>:8080)
scripts/run_local_mac.sh --token  # telefonda girilecek token
scripts/run_local_mac.sh --stop
```

Mac'in Wi-Fi IP adresi değişirse (DHCP) görüntü bağlanmaz: script'i tekrar çalıştırın ya da modemden IP'yi sabitleyin. Apple M1'de PS1 (Ace Combat 2) 30 fps, emülatör ~%89 tek çekirdek.

## Sistemler ve oyun ekleme (R36S tarzı klasörler)

Sunucuda `/srv/retrocloud/roms/<sistem>/` klasörüne konan her oyun, launcher'da o sistemin altında kendiliğinden listelenir (~15 sn içinde, yeniden başlatma gerekmez). Yerelde `game-worker/roms/<sistem>/` klasörüne koyup `scripts/deploy.sh` çalıştırmak da aynı işi görür (dosyalar git'e ve Docker imajına girmez).

| Klasör | Sistem | Emülatör (libretro core) | Dosya türleri |
|---|---|---|---|
| `nes` | NES / Famicom | Nestopia | .nes .unf |
| `snes` | Super Nintendo | Snes9x | .sfc .smc |
| `gb`, `gbc` | Game Boy / Color | Gambatte | .gb / .gbc |
| `gba` | Game Boy Advance | mGBA | .gba |
| `sms`, `gg`, `md` | Master System, Game Gear, Mega Drive | Genesis Plus GX | .sms / .gg / .md .gen .smd .bin |
| `segacd` | Mega CD | Genesis Plus GX | .chd .cue (BIOS gerekir) |
| `psx` | PlayStation | PCSX ReARMed (dahili HLE BIOS) | .chd .cue .pbp .m3u |
| `pce` | PC Engine | Beetle PCE Fast | .pce |
| `ws` | WonderSwan | Beetle WonderSwan | .ws .wsc |
| `atari2600` | Atari 2600 | Stella 2014 | .a26 .bin |
| `arcade`, `neogeo` | Arcade, Neo Geo | FinalBurn Neo | .zip (romset adı değişmemeli; Neo Geo için `bios/neogeo.zip`) |

El konsollarının SD kart düzenindeki klasör adları da tanınır (`megadrive`, `genesis`, `mastersystem`, `gamegear`, `pcengine`, `wonderswan`, `fbneo`, `mame`, `ps1` …; tam liste `systems.json` → `folders`). Not: `mame` klasöründeki setler FinalBurn Neo ile açılır; FBNeo'nun desteklemediği MAME setleri çalışmaz.

BIOS dosyaları `roms/bios/` klasörüne konur (her oturuma salt okunur bağlanır). PS1 BIOS'suz çalışır; gerçek BIOS (`scph5501.bin` vb.) koyarsanız uyumluluk artar. Sistem listesi `game-worker/config/systems.json`'da; yeni sistem eklemek için core'u Dockerfile'a, satırı bu dosyaya ekleyin.

**Yasal not:** Telifli oyunları biz dağıtmıyoruz. Sadece sahip olduğunuz oyunların kendi yedeklerini, kendi sunucunuzda, kendiniz için kullanın. Repo ve imaj hiçbir telifli ROM/BIOS içermez.

Launcher (`/`): ◀▶ sistem, ▲▼ oyun, A/Enter oyna, L/R 10'ar atla. Oyun içinde SELECT+START'ı ~1 sn basılı tutmak (ya da ✕) oturumu kapatıp listeye döner.

## Testler

```bash
cd game-worker
/usr/bin/python3 -m pytest -q tests                                    # 18 test
node tests/e2e_stream.mjs    http://127.0.0.1:8080 <worker-token> 20   # Playwright gerekir
node tests/e2e_isolation.mjs http://127.0.0.1:8080 <worker-token> 20
scripts/bench_encoder.sh                                               # sadece x264 maliyeti (kök dizinden)
```

## Yapılandırma (ortam değişkenleri)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `RC_WORKER_TOKEN` | (zorunlu) | Control Plane → worker API anahtarı, en az 16 karakter |
| `RC_DEV` | `0` | `1`: token yoksa rastgele üretir |
| `RC_BIND` / `RC_PORT` | `127.0.0.1` / `8080` | Dışarı Caddy üzerinden açılır |
| `RC_MAX_SESSIONS` | `2` | Eşzamanlı oturum sınırı |
| `RC_VIDEO_WIDTH/HEIGHT/FPS` | `1280/720/30` | Yakalama boyutu ve hızı |
| `RC_VIDEO_BITRATE_KBPS` | `3000` | x264 hedef bitrate |
| `RC_X264_PRESET` | `ultrafast` | `superfast` daha iyi kalite, ~%40 daha fazla CPU |
| `RC_STUN_URL` | `stun://stun.l.google.com:19302` | Boş = STUN yok |
| `RC_PUBLIC_IP` | | GCE 1:1 NAT için dış IP (host adayı yeniden yazılır) |
| `RC_RTP_PORT_MIN/MAX` | `50000/50100` | Firewall'daki UDP aralığıyla aynı olmalı |
| `RC_TURN_HOST` / `RC_TURN_SECRET` | | coturn kullanılıyorsa |
| `RC_DATA_DIR` | `/var/lib/retrocloud` | Oturum dizinleri (kayıtlar, loglar) |
| `RC_ROMS_DIR` / `RC_GAMES_FILE` | `game-worker/roms`, `config/games.json` | Katalog ve ROM'lar |

## Nasıl çalışır (kısa)

1. `POST /api/sessions` → worker boş bir X ekranı seçer, oturuma özel Xvfb, PulseAudio ve RetroArch başlatır, rastgele bir oturum token'ı döner.
2. Oyuncu sayfası token'ı URL fragment'ından okur (sunucuya veya loglara gitmez) ve WebSocket'te ilk mesaj olarak gönderir.
3. Worker o oturum için bir GStreamer pipeline'ı kurar: `ximagesrc → x264 → RTP` ve `pulsesrc → Opus → RTP`, ikisi de `webrtcbin`'e. SDP offer / answer ve ICE adayları WebSocket üzerinden gider.
4. Girdi WebRTC data channel'dan bit maskesi olarak gelir ve XTEST ile **sadece o oturumun** X ekranına tuş olayı olarak verilir.
5. Bağlantı koparsa tuşlar bırakılır, oyun çalışmaya devam eder, oyuncu sayfası kendiliğinden yeniden bağlanır.

## Oyun lisansları

Repoda telif hakkı korunan ROM yok ve olmamalı. Tek dahil içerik `game-worker/roms/testpad/`: bu proje için yazılmış küçük bir NES programı (MIT), kaynağıyla birlikte (`ca65 testpad.s && ld65 -C nes.cfg ...`). Yeni oyun eklerken sadece açık kaynak, public-domain veya dağıtım izni açık homebrew kullanın ve lisansını `games.json`'a yazın. Core lisansları ve PS1 BIOS için bkz. [docs/roadmap.md](docs/roadmap.md#lisans-ve-hukuk-notları).
