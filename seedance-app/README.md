# Seedance Studio

A small image→video generator with **pluggable providers**:
- **Seedance 2.0** via fal.ai or Replicate (API)
- **Self-hosted** open model (LTX/Wan) via a RunPod serverless endpoint

## Run
```bash
npm install
cp .env.example .env   # set PROVIDER + keys (or leave PROVIDER=demo)
npm start              # http://localhost:3000
```

## Providers (env `PROVIDER`)
| value | needs | what it does |
|---|---|---|
| `demo` | nothing | returns a bundled sample clip — for testing the flow/UI |
| `fal` | `FAL_KEY` | Seedance 2.0 (image/text-to-video) on fal.ai |
| `replicate` | `REPLICATE_API_TOKEN` | Seedance 2.0 on Replicate |
| `runpod` | `RUNPOD_API_KEY`, `RUNPOD_ENDPOINT_ID` | your self-hosted LTX/Wan worker |

The UI shows which providers have credentials (API / SELF-HOSTED / NO KEY / OFFLINE badges).
