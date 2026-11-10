# Phase 0 benchmark raporu

Tarih: 2026-11-10. Bütün sayılar gerçekten çalıştırılmış testlerden geliyor; ham JSON'lar `tests/results/` altında.

## Ortam

- Bulut sandbox konteyneri (GCP değil): Ubuntu 24.04.5, 4 vCPU Intel Xeon @ 2.1 GHz, 16 GB RAM, GPU yok, `/dev/dri` yok, `/dev/uinput` yok.
- Mesa 25.2.8 llvmpipe, RetroArch 1.18.0, Nestopia core, GStreamer 1.24.2, Python 3.12.
- İstemci: Playwright ile headless Chromium, **aynı makinede** (gerçek ağ yok).
- İçerik: TestPad (bu proje için yazılmış NES ROM'u), kayan gürültü arka planı açık.
- Ayar: 1280x720, 30 FPS, x264 `ultrafast` + `zerolatency`, 3000 kbps, keyint 60, Opus 96 kbps.

## Sonuçlar

| Test | Doğrudan (host) | Docker (non-root, read-only, cap_drop ALL) |
|---|---|---|
| Uçtan uca kontroller (9 adet: bağlantı, video, H.264, ses var, A tuşunda ton, klavye, gamepad, gecikme, yeniden bağlanma) | 9/9 geçti | 9/9 geçti |
| İki oturum kontrolleri (5 adet: ikisi de bağlı, girdi izolasyonu, çapraz token reddi, A kapanınca B devam, sadece B kalır) | 5/5 geçti | 5/5 geçti |
| Tarayıcı FPS | 30.0 | 30.0 |
| Video bitrate | 2989 kbps | 2981 kbps |
| Kayıp paket / düşen kare | 0 / 0 | 0 / 0 |
| Girdi → ekran medyan / en çok (ağ hariç) | 84 / 116 ms | 107 / 137 ms |
| RetroArch CPU (1 oturum) | 30.8% | 33.3% |
| Xvfb / PulseAudio CPU | 7.3% / 2.2% | 7.1% / 2.1% |
| Worker süreci, 2 oturum toplam (yakalama + x264 + Opus + WebRTC) | 63.6% | 64.2% |
| RetroArch RAM | 174 MB | 180 MB |
| pytest | 18/18 geçti | (imaj içinde çalıştırılmadı) |
| Terraform validate (GCP + Azure) | geçti | |

Konteyner içinde gecikme medyanı ~20 ms daha yüksek çıktı. Tek ölçüm turu var ve aynı makinede tarayıcı da çalışıyordu; fark gürültü olabilir, Phase 1'de GCP'de tekrar ölçülecek.

Kodlayıcı tek başına (videotestsrc, en kötü içerik): 720p ultrafast 30%, superfast 43%, veryfast 61%; 540p ultrafast 20%; 480p ultrafast 17% (`tests/results/phase0-encoder-bench.txt`).

## Kapasite tahmini

Oturum başına ≈ 0.72 vCPU (NES sınıfı, 720p30). e2-standard-4 üzerinde 2 oturum ≈ 1.45 vCPU + işletim sistemi, Caddy, Docker payı. GCP e2 vCPU'ları hyperthread olduğu ve sandbox CPU'su farklı olduğu için **GCP'de yeniden ölçülmeden kapasite garantisi verilmez.**

## Phase 1 için kabul kriterleri ve ölçüm planı (GCP)

1. Aynı iki Playwright testi VM'e karşı **internet üzerinden** (kullanıcının bilgisayarından) çalıştırılacak: FPS ≥ 29, kayıp < %1, RTT ve girdi → ekran süresi raporlanacak.
2. Gerçek gamepad ile manuel test (Chrome + Xbox/PS kumanda), Safari, Android TV tarayıcısı.
3. 30 dakikalık iki oturumlu dayanıklılık testi: CPU, RAM, bitrate grafiği (`/api/sessions/{id}/metrics`).
4. GB, Mega Drive, SNES ve PS1 için yasal homebrew ile core başına CPU ölçümü.
5. Çözünürlük denemesi: 1280x720 vs 768x720 (NES için 3x tamsayı ölçek) vs 854x480.
