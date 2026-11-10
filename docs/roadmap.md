# Yol haritası ve geliştirme planı

Kural: bir sonraki aşamaya, mevcut aşama ölçülüp doğrulandıktan sonra geçilir.

## Phase 0 — Fizibilite ✅ (yerelde, 2026-11-10)

Bitti: yazılımsal rendering, headless RetroArch, sanal ekran, CPU H.264, WebRTC, ses, girdi, Docker izinleri, 2 oturum izolasyon denemesi. Ayrıntı: `feasibility.md`, `benchmark-phase0.md`.
Açık kalan: bulutta doğrulama (kullanıcı onayı gerekiyor).

## Phase 1 — Tek oyuncu, GCP üzerinde (sıradaki)

| # | İş | Çıktı / kabul |
|---|---|---|
| 1 | Onay sonrası `terraform apply` + `scripts/deploy.sh` | VM ayakta, HTTPS çalışıyor |
| 2 | Kendi bilgisayarınızdan TestPad ile oynama | Görüntü, ses, kumanda; ekran görüntüsü |
| 3 | Playwright testlerini internet üzerinden VM'e karşı çalıştırma | FPS, kayıp, RTT, girdi → ekran süresi |
| 4 | Yasal homebrew seti (GB, MD, SNES, NES) ve katalog | Lisansları `games.json`'da kayıtlı |
| 5 | PS1: güncel PCSX ReARMed core + HLE BIOS denemesi | Çalışıyorsa CPU ölçümü; çalışmıyorsa alternatif |
| 6 | Çözünürlük / preset ayarı (768x720 tamsayı ölçek, 480p) | Benchmark tablosu |
| 7 | Safari, Android TV, mobil dokunmatik manuel test | Uyumluluk listesi |
| 8 | Gerekirse TURN (coturn) | Mobil ağdan bağlantı |

## Phase 2 — İki oyuncu

Worker zaten `RC_MAX_SESSIONS=2` ile iki bağımsız oturum çalıştırıyor ve yerelde test edildi. Kalan: GCP'de iki farklı ağdan iki gerçek oyuncu, 30 dk dayanıklılık, oturum başına CPU kotası (cgroup v2 `cpu.max` ile oturum başına sınır), ayrı kayıt dosyalarının kalıcı diskte doğrulanması.

## Phase 3 — Management API (FastAPI)

`backend/` altında: `GET /health`, `GET /games`, `GET /workers`, `POST /sessions`, `GET /sessions/{id}`, `DELETE /sessions/{id}`, `GET /sessions/{id}/metrics`. PostgreSQL (users, games, workers, sessions, usage_events), parola + JWT (kısa ömürlü access + refresh) veya HttpOnly cookie oturumu, oturum sahipliği kontrolü, worker'a `RC_WORKER_TOKEN` ile proxy. pytest + test veritabanı.

## Phase 4 — Web panel

React (Vite) veya Next.js: Login, Game Library, My Sessions, Launch Game, Streaming Player (bugünkü `play.html` bileşeni), Admin Dashboard (worker kapasitesi, aktif oturumlar, metrikler).

## Phase 5 — SaaS hazırlığı (sadece tasarım, `architecture.md` bölüm 5)

Multi-tenancy, GPU worker havuzu (Wolf/Selkies), scheduler, autoscaling, bölge seçimi, kuyruk, faturalandırma, kullanım ölçümü, rate limiting, audit log.

## Lisans ve hukuk notları

- Telif hakkı korunan ROM'lar repoya girmez (`.gitignore`). Test içeriği bu proje için yazılmış TestPad (MIT). Homebrew eklerken lisansı `games.json`'daki `license` alanına yazın.
- RetroArch GPLv3. Kendi sunucunuzda çalıştırıp yayınlamak dağıtım sayılmaz; ama değiştirilmiş RetroArch'ı başkalarına dağıtırsanız kaynak kodu vermeniz gerekir. Core lisansları farklı: snes9x **ticari kullanımı yasaklar**, Genesis Plus GX ve beetle/mednafen türevlerinin lisansları core bazında incelenmeli. SaaS'tan önce core başına lisans tablosu çıkarılmalı.
- PS1 BIOS Sony'nin telifidir; dağıtılamaz. HLE BIOS'lu core veya kullanıcının kendi BIOS'u.
- Steam/Proton ile ticari cloud gaming: Steam Abonelik Sözleşmesi ve oyun yayıncılarının EULA'ları oyunları başkalarına uzaktan oynatmayı genelde kısıtlar; ticari model için yayıncılarla lisans anlaşması gerekir. Bu hukuki bir değerlendirme değildir, avukata danışılmalı.
