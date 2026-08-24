# Certificados raiz da Apple

Contém `AppleRootCA-G3.cer` (baixado de
https://www.apple.com/certificateauthority/AppleRootCA-G3.cer), o
certificado raiz que ancora a cadeia de assinatura das transações
StoreKit 2 — é o que a `app-store-server-library` usa em
`SignedDataVerifier` para validar a assinatura JWS enviada pelo app em
`POST /ai-credits/apple/purchases`.

Se a Apple rotacionar/adicionar um root cert exigido pela cadeia de
assinatura no futuro, baixe o novo arquivo `.cer` da mesma seção
"Apple Root Certificates" e coloque aqui — todos os `.cer` deste
diretório são carregados automaticamente.

O caminho deste diretório é configurável via `APPLE_ROOT_CERTIFICATES_DIR`
(default: este diretório). Os testes automatizados não dependem destes
arquivos — eles mockam
`app.credits.apple_verification.verify_signed_transaction` diretamente.
