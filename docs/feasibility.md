# Phase 0: Teknik fizibilite

Tarih: 2026-11-10. Bu belge, GPU olmadan tarayıcıya retro oyun yayınının teknik risklerini ve Phase 0'da **gerçekten çalıştırılan** testlerin sonuçlarını içerir.

## 1. Kısa sonuç

GPU'suz, tamamen CPU üzerinde çalışan zincir (RetroArch + Mesa llvmpipe → Xvfb → x264 → WebRTC → tarayıcı) **çalışıyor ve ölçülebilir**. Tek oyunculu prototip uçtan uca testlerin tamamını geçti. İki bağımsız oturum da aynı makinede birbirini etkilemeden çalıştı (Phase 2'nin ön denemesi).

Önemli kısıt: Testler bir **bulut sandbox konteynerinde** yapıldı (Ubuntu 24.04, 4 vCPU Intel Xeon @ 2.1 GHz, 16 GB RAM), **GCP VM'inde değil**. Tarayıcı (headless Chromium) sunucuyla aynı makinedeydi, yani gerçek internet, NAT ve paket kaybı test edilmedi. Gecikme sayıları bu yüzden "ağ hariç" değerlerdir.

## 2. Risk tablosu

| Risk | Durum | Kanıt / not |
|---|---|---|
| GPU'suz yazılımsal rendering | ✅ Yerelde doğrulandı | `glxinfo`: `llvmpipe (LLVM 20.1.2, 256 bits)`, OpenGL 4.5. RetroArch `gl` sürücüsüyle çalıştı. |
| RetroArch'ı headless çalıştırma | ✅ Yerelde doğrulandı | Xvfb üzerinde tam ekran, `pause_nonactive=false`. Nestopia core ile TestPad ROM'u. |
| Sanal ekran | ✅ Yerelde doğrulandı | Oturum başına ayrı Xvfb (`:100`, `:101`...). |
| CPU üzerinden H.264 | ✅ Yerelde doğrulandı | x264 `ultrafast`/`zerolatency`, 1280x720@30, tarayıcıda `video/H264` decode edildi. |
| WebRTC aktarımı | ✅ Yerelde doğrulandı | GStreamer `webrtcbin` 1.24.2 → Chromium. Video + Opus ses + data channel. |
| Ses | ✅ Yerelde doğrulandı | Oturum başına ayrı PulseAudio; A tuşuyla çalınan 440 Hz ton tarayıcıda RMS 0.127 (sessizlikte 0). |
| Gamepad input injection | ✅ Yerelde doğrulandı (XTEST ile) | Tarayıcı Gamepad API → data channel → oturumun kendi X ekranına XTEST. uinput **kullanılmadı** (aşağıya bakın). |
| Docker izinleri | ✅ Yerelde doğrulandı | Non-root, read-only, `cap_drop ALL` konteynerde bütün uçtan uca testler geçti. Privileged, `/dev/uinput`, `/dev/dri` gerekmiyor (bölüm 4). |
| GCP VM'de çalışma | ⚠️ Doğrulanmadı | Kullanıcı onayı bekliyor. Aynı Ubuntu 24.04 paketleri kullanıldığı için risk düşük. |
| İnternet üzerinden NAT/STUN/TURN | ⚠️ Doğrulanmadı | GCE 1:1 NAT için `RC_PUBLIC_IP` ile host aday yeniden yazımı eklendi; coturn opsiyonel ve test edilmedi. |
| Safari / Android TV / mobil | ⚠️ Doğrulanmadı | H.264 Constrained Baseline seçildi (Safari ve Android TV'de donanım decode için en uyumlu profil). |
| PS1 ve ağır SNES oyunları | ⚠️ Ölçülmedi | Yasal test ROM'u yok. PS1 BIOS lisans sorunu var (bölüm 7). |

## 3. Ölçülen sonuçlar (gerçek çalıştırma)

Ham çıktılar: `tests/results/phase0-*.json|txt`.

### 3.1 Tek oyuncu, 1280x720 @ 30 FPS, x264 ultrafast, hedef 3000 kbps

TestPad ROM'unun kayan "gürültü" arka planı açıkken (kodlayıcı için zor içerik), 20 saniyelik örnek:

| Metrik | Değer |
|---|---|
| Tarayıcıda FPS | 30.0 |
| Sunucuda kodlanan FPS | 29.7 |
| Video bitrate | ~2950–2990 kbps (hedef 3000) |
| Ses | Opus 48 kHz (sessizlikte ~2 kbps, DTX benzeri davranış) |
| Kayıp paket / düşen kare | 0 / 0 (yerel ağ) |
| Tarayıcı decode süresi | ~1.4 ms/kare |
| Jitter buffer | ~4 ms |
| RetroArch CPU | ~31% (1 vCPU = 100%) |
| Xvfb CPU | ~7% |
| PulseAudio CPU | ~2% |
| RetroArch RAM | ~174 MB |
| Girdi → ekranda hareket (tuşa basıştan karenin tarayıcıda değişmesine) | medyan 84 ms, en çok 116 ms (10 ölçüm, ağ hariç) |
| Yeniden bağlanma | Signaling soketi kesildikten ~3.4 s sonra görüntü ve girdi geri geldi |

"Girdi → ekran" süresinin içinde: emülatörün bir sonraki kareyi üretmesi (NES 60 Hz), Xvfb yakalama aralığı (30 FPS = 33 ms), x264, RTP, tarayıcı jitter buffer ve decode var. İnternet üzerinde buna RTT eklenir (Türkiye → Frankfurt tipik ~40–60 ms, ölçülmedi).

### 3.2 İki eşzamanlı oturum (Phase 2 ön denemesi)

| Kontrol | Sonuç |
|---|---|
| A'daki girdi sadece A'yı hareket ettirdi | ✅ A: 159 → 228 px, B: 159.5 → 159.5 px |
| A'nın token'ı ile B'nin soketine bağlanma | ✅ Reddedildi (WebSocket kapanış kodu 4401) |
| A durdurulunca B'nin yayını | ✅ 3 saniyede 90 kare (kesintisiz 30 FPS) |
| FPS (A / B) | 30.0 / 29.9 |
| Bitrate (A / B) | 2986 / 3004 kbps |
| RetroArch CPU (A / B) | 30.1% / 30.2% |
| Worker süreci (2 oturumun yakalama + x264 + Opus + WebRTC toplamı) | 63.6% |

**Oturum başına toplam ≈ 0.72 vCPU** (RetroArch 0.30 + kodlama/yayın 0.32 + Xvfb 0.07 + Pulse 0.02). İki oyuncu ≈ 1.45 vCPU. Bu, 4 vCPU'luk bir makinede (e2-standard-4) iki NES sınıfı oturum için yeterli pay bırakıyor. 8 vCPU hedefi PS1 ve daha ağır içerik için gerekebilir; Phase 1'de GCP üzerinde ölçülecek.

### 3.3 Kodlayıcı darboğazı (emülatörden ayrı ölçüm)

`scripts/bench_encoder.sh`: GStreamer `videotestsrc` → x264, canlı 30 FPS, 10 s. CPU değeri test deseni üretimini de içerir (yani gerçek maliyetten biraz yüksek).

| İçerik | Çözünürlük | Preset | CPU (1 vCPU = 100%) |
|---|---|---|---|
| snow (en kötü durum) | 1280x720 | ultrafast | 30.2% |
| snow | 1280x720 | superfast | 42.6% |
| snow | 1280x720 | veryfast | 60.5% |
| snow | 960x540 | ultrafast | 20.3% |
| snow | 854x480 | ultrafast | 17.4% |
| ball (kolay) | 1280x720 | ultrafast | 21.8% |

CPU yetmezse sıra: (1) yakalama çözünürlüğünü tamsayı ölçeğe indir (NES için 768x720 = 3x, 1280x720'nin %60'ı kadar piksel, siyah kenar yok), (2) 854x480, (3) FPS 30 → 25, (4) emülatör core'unu değiştir. `superfast`'e geçmek kaliteyi artırır ama CPU'yu ~%40 yükseltir.

## 4. Konteyner testi

Worker Docker imajı (`game-worker/Dockerfile`, 577 MB) derlendi ve compose dosyasındaki kısıtlarla çalıştırıldı: UID 10001, `--read-only`, `/tmp` tmpfs, `--cap-drop ALL`, `no-new-privileges`, 3.5 CPU / 6 GB / 512 PID limiti. Privileged mod, `/dev/uinput` veya `/dev/dri` verilmedi. Tek oyunculu (9/9) ve iki oturumlu (5/5) uçtan uca testlerin hepsi konteyner içinde de geçti. Ayrıntı: `docs/benchmark-phase0.md`.

## 5. Teknoloji karşılaştırması ve seçim

| Seçenek | Tarayıcı | GPU'suz | Oturum başına izolasyon | Konteyner | Not |
|---|---|---|---|---|---|
| **Sunshine** (+ Moonlight) | ❌ Moonlight istemcisi gerekir | ✅ yazılımsal kodlama var | ⚠️ Host başına tek ana oturum için tasarlanmış | ✅ | Masaüstü oyun için çok iyi; tarayıcı hedefimize uymuyor. |
| **Wolf** (Games on Whales) | ❌ Moonlight protokolü | ✅ x264 destekli | ✅ Çok kullanıcı, oturum başına konteyner | ✅ ama `/dev/uinput`, udev ve genişletilmiş yetkiler ister | GPU worker havuzu (Phase 5) için en güçlü aday. |
| **Selkies** (selkies-gstreamer) | ✅ WebRTC | ✅ x264 | ⚠️ Konteyner başına tam masaüstü | ✅ | Bizim yaptığımıza en yakın mimari; tam masaüstü ağır. Referans ve yedek plan. |
| **Neko** | ✅ WebRTC | ✅ | ❌ Paylaşılan tek oturum (birlikte izleme için) | ✅ | "Herkes kendi oyunu" modeline uymuyor. |
| **aiortc** (saf Python WebRTC) | ✅ | ✅ | ✅ | ✅ | Kare dönüşümleri Python'da; 720p30'da CPU israfı. |
| **Özel worker: GStreamer webrtcbin** ✅ seçildi | ✅ | ✅ | ✅ Oturum başına X ekranı, PulseAudio, dizin | ✅ Yetkisiz | İnce katman: capture, encode, signaling, input ve izolasyonu biz kontrol ediyoruz. |

Seçim gerekçesi: Hedef tarayıcı olduğu için Moonlight tabanlı Sunshine ve Wolf ilk MVP'ye uymuyor. Selkies'in bileşenleri (GStreamer + webrtcbin + x264) doğru ama tam masaüstü yerine "sadece oyun penceresi" yayınlamak için kendi ince worker'ımız daha az CPU ve daha net izolasyon veriyor. Bu seçim yukarıdaki testlerde **GPU'suz, iki bağımsız oturum, tarayıcı ve konteyner** koşullarıyla doğrulandı. Steam/Proton GPU havuzu için ileride Wolf veya Selkies'i ayrı bir worker tipi olarak eklemek mimaride öngörüldü (`docs/architecture.md`).

## 6. Girdi: neden uinput değil de XTEST?

- `/dev/uinput` çekirdek modülü ve cihaz erişimi ister; Docker'da `--device /dev/uinput` ve çoğu zaman ek yetki gerekir. GCE Ubuntu çekirdeğinde modül var ama sandbox konteynerimizde `/dev/uinput` yoktu.
- uinput ile oluşturulan sanal gamepad **sisteme geneldir**: aynı hosttaki her RetroArch onu görebilir. İki oyuncuyu ayırmak için udev kuralları ve cihaz eşleme gerekir. Yanlış yapılandırma = bir oyuncunun diğerinin oyununu kontrol etmesi.
- XTEST ile her oturum **kendi X ekranına** tuş gönderir. Başka bir RetroArch'ın bu olayları görmesi mümkün değil. İzolasyon yapıdan geliyor, ayrıcalık gerekmiyor.
- Tarayıcı tuş kodu göndermez; sabit bir beyaz listeden mantıksal buton adı (`up`, `a`, `start`...) gönderir. RetroArch kısayolları (menü, çıkış, save state) yapılandırmada kapalı. Kullanıcı bağlantısı kopunca bütün tuşlar bırakılır.
- Sınır: sadece dijital butonlar. Analog çubuk (PS1 DualShock analog, N64) için ileride ya oturum başına ayrı uinput cihazı + udev eşleme ya da RetroArch'ın ağ girdi arayüzü (`network_remote`) değerlendirilecek.

## 7. Platformlar ve emülatörler

| Platform | Core (Ubuntu paketi) | Durum | Not |
|---|---|---|---|
| NES | nestopia | ✅ test edildi | TestPad ROM. |
| Game Boy / GBC | gambatte | Kurulu, test edilmedi | Hafif. |
| SNES | snes9x | Kurulu, test edilmedi | Ağır SNES oyunları (SuperFX) daha fazla CPU ister. |
| Mega Drive | genesis_plus_gx | Kurulu, test edilmedi | Hafif. |
| PS1 | mednafen_psx (beetle) | Kurulu, test edilmedi | **BIOS gerektirir.** Sony BIOS'u dağıtılamaz. Ubuntu'daki beetle sürümü 2015 tarihli. Öneri: libretro buildbot'tan güncel **PCSX ReARMed** (HLE BIOS ile çalışabilir) veya kullanıcının kendi BIOS'u. Phase 1'de ölçülecek. |

## 8. Phase 0'da bulunan ve düzeltilen hatalar

Aşağıdakiler testler sırasında gerçekten yaşandı:

1. **PyGObject referans hatası**: `webrtcbin`'in `ice-agent` özelliğini okumak bir referansı fazladan bırakıyor, ilk teklifte pipeline çöküyordu. Eksik referans `ctypes` ile ekleniyor (`worker/stream.py`, `_ice_agent`).
2. **Ekran çakışması (izolasyon hatası)**: Önceki bir çökmeden kalan Xvfb `:100`'ü tutarken yeni oturum kendi Xvfb'si açılamadığı halde o ekrana bağlandı; yani oyun başka bir oturumun ekranına çiziliyordu. Düzeltme: boş ekran seçerken soket ve kilit dosyaları kontrol ediliyor ve kendi Xvfb sürecimiz ölmüşse oturum hata veriyor.
3. **Yeniden bağlanmada siyah ekran**: Eski `MediaStream` yeni bağlantıda yeniden kullanılıyordu. Kopuşta temizleniyor.

## 9. Henüz test edilmeyenler (dürüst liste)

- GCP VM üzerinde çalışma, gerçek internet, NAT, TURN, paket kaybı ve uzun süreli kararlılık.
- Fiziksel gamepad (test, Gamepad API'si taklit edilerek yapıldı), Safari, Android TV, mobil dokunmatik kontroller.
- SNES / Mega Drive / GB / PS1 gerçek oyun CPU ölçümleri.
- Let's Encrypt sertifikası alma (Caddy + sslip.io), Ops Agent loglama, bütçe alarmı, gece kapatma ve boşta kapatma scriptleri. Bunlar yazıldı ama bulutta çalıştırılmadı.
