# Deploy kılavuzu (GCP)

> Bu adımlar **ücretli kaynak oluşturur.** Phase 0'da hiçbiri çalıştırılmadı; onayınızı bekliyor. Önce `scripts/cost_estimate.py` ile tahmini maliyeti görün.

## 0. Ön koşullar

- GCP hesabı, deneme kredisi görünür durumda (Konsol → Billing → Credits).
- Yerel araçlar: `gcloud`, `terraform >= 1.6`, `ssh`, `rsync`.
- SSH anahtarı: `ssh-keygen -t ed25519` (yoksa).

## 1. Proje ve faturalandırma

```bash
gcloud auth login
gcloud auth application-default login
gcloud projects create retrocloud-mvp-<rastgele> --name="RetroCloud MVP"
gcloud billing accounts list                       # deneme faturalandırma hesabının ID'si
gcloud billing projects link retrocloud-mvp-<..> --billing-account=XXXXXX-XXXXXX-XXXXXX
gcloud config set project retrocloud-mvp-<..>
# Terraform (billing_project override) needs these before its first refresh:
gcloud services enable serviceusage.googleapis.com cloudresourcemanager.googleapis.com iam.googleapis.com compute.googleapis.com
```

Deneme projelerinde vCPU kotası düşük olabilir ve deneme sırasında kota artışı istenemez. 4 vCPU'luk e2-standard-4 genelde sığar; Konsol → IAM → Quotas'ta `CPUS` (europe-west3) ve `CPUS_ALL_REGIONS` değerine bakın.

## 2. Maliyet tahmini (zorunlu adım)

```bash
python3 scripts/cost_estimate.py --machine e2-standard-4 --hours 120 --players 1
```

## 3. Terraform

```bash
cd infrastructure/terraform/gcp
cp terraform.tfvars.example terraform.tfvars
# project_id, admin_cidrs (curl -4 ifconfig.me + /32), istenirse billing_account_id düzenleyin
terraform init
terraform plan        # oluşturulacak her kaynağı gösterir, ücret oluşturmaz
terraform apply       # ÜCRETLİ: VM, disk, IP. Onay sorar.
```

Oluşan kaynaklar: VPC + subnet, 3 firewall kuralı (SSH sadece sizin IP'niz, 80/443, UDP 50000-50100), VM servis hesabı (sadece log/metrik yazma), e2-standard-4 VM (Shielded VM, 20 GB boot), 10 GB kalıcı data diski, gece 02:00 durdurma programı, 4 saatlik `max_run_duration`, isteğe bağlı bütçe alarmı.

Bütçe alarmı: `billing_account_id` boşsa Terraform oluşturmaz; Konsol → Billing → Budgets & alerts'ten 25 USD'lik bir bütçe ekleyin. **Bütçe alarmı harcamayı durdurmaz, sadece e-posta gönderir.**

## 4. Uygulamayı yükleme

```bash
cd ../../..
scripts/deploy.sh
```

Script: cloud-init'in bitmesini bekler, kodu ve yasal ROM'ları `rsync` ile kopyalar, imajı VM'de derler, servisi başlatır ve `https://<ip-tireli>.sslip.io` adresini yazar. Worker token'ı VM'de `/srv/retrocloud/env/worker.env` dosyasında (0600), repoda değil.

İlk sertifika: Caddy, Let's Encrypt'ten birkaç saniye içinde alır. sslip.io kısıtlanırsa kendi alan adınızı `RC_DOMAIN`'e yazın.

## 5. Günlük kullanım

```bash
scripts/vm.sh start    # VM'i aç (IP değişir, yeni URL yazılır)
scripts/vm.sh stop     # kapat: vCPU/RAM ücreti durur, disk ücreti (~3.6 USD/ay) sürer
scripts/vm.sh status
scripts/vm.sh ssh
scripts/vm.sh logs     # Cloud Logging'den son 1 saat
```

Otomatik kapanma: (1) 30 dk oyun yoksa ve SSH ile bağlı kimse yoksa VM kendini kapatır, (2) her gece 02:00, (3) açıldıktan 4 saat sonra (`max_run_hours`).

## 6. Her şeyi silme

```bash
scripts/destroy.sh     # 'destroy' yazmanızı ister, sonra kalan disk/IP/snapshot'ları listeler
```

## 7. Loglama ve izleme

- Konteyner logları: JSON, 10 MB × 3 dönüş. Ops Agent, `/var/lib/docker/containers/*/*.log` dosyalarını Cloud Logging'e gönderir.
- Host metrikleri: Ops Agent `hostmetrics` (CPU, RAM, disk, ağ) → Cloud Monitoring.
- Uygulama metrikleri: `GET /api/sessions/{id}/metrics` (süreç başına CPU/RAM, kodlanan FPS ve bitrate, host yükü).
- Sağlık: `GET /health` (Docker HEALTHCHECK de bunu kullanır).

## 8. Azure (alternatif, taslak)

`infrastructure/terraform/azure/main.tf` aynı düzeni kurar (`terraform validate` geçiyor, hiç uygulanmadı). Farklar: cloud-init'teki metadata çağrıları Azure IMDS'e (`http://169.254.169.254/metadata/instance?api-version=2021-02-01`, başlık `Metadata: true`) çevrilmeli; Standard SKU statik IP VM kapalıyken de ücretlenir; `max_run_duration` karşılığı yok, sadece günlük otomatik kapatma var.
