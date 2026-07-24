# Acesso Remoto Local (PyQt5 + Socket)

Aplicação desenvolvida em Python para **controle e acesso remoto de computadores em redes locais (LAN/Wi-Fi)**. O sistema utiliza sockets TCP, transmissão de frames comprimidos em tempo real via OpenCV/MSS e controle nativo de mouse e teclado via Pynput, contando com uma interface gráfica moderna construída em **PyQt5**.

> **Nota:** Este projeto foi otimizado e configurado para funcionar em pequenas redes caseiras ou corporativas locais, facilitando a conexão direta entre máquinas sem burocracia ou intermediários externos.

---

## 🚀 Funcionalidades

* **Painel de Controle Unificado:** Uma tela inicial intuitiva com escolha direta entre **Conectar** (Cliente) ou **Receber Conexão** (Servidor).
* **Múltiplos Monitores:** Suporte nativo para alternar a visualização e o controle entre o Monitor 1 e o Monitor 2 em tempo real.
* **Mapeamento Preciso de Coordenadas:** Conversão automática de escala e proporção da tela, garantindo que o cursor do mouse na máquina remota corresponda exatamente ao local exibido, mesmo com diferenças de resolução ou proporção (com suporte a múltiplos monitores e cálculo de offset global).
* **Persistência de IP:** Salva o último endereço IP conectado em um arquivo de configuração local (`remote_config.json`), agilizando novas conexões.
* **Barra de Métricas em Tempo Real:** Exibe o nome do host conectado, taxa de atualização de quadros por segundo (**FPS**), consumo de banda (**Mbps**) e hora atual na barra de título.
* **Modo Maximizado Sem Bordas:** Ajuste dinâmico da imagem mantendo a proporção correta (*KeepAspectRatio*) ao redimensionar ou maximizar a janela.

---

## 🛠️ Tecnologias Utilizadas

* **Python 3.x**
* **PyQt5** (Interface Gráfica e multithreading)
* **OpenCV** (`cv2` para decodificação e compressão JPEG de vídeo)
* **MSS** (Captura de tela de alta performance)
* **Pynput** (Injeção de eventos de mouse e teclado)
* **Socket / Pickle / Struct** (Comunicação TCP e serialização de dados)

---

## 📦 Instalação e Execução

### 1. Clonar o repositório e instalar as dependências
Certifique-se de ter o Python instalado e execute os comandos abaixo no terminal:

```bash
git clone [https://github.com/SEU_USUARIO/NOME_DO_REPOSITORIO.git](https://github.com/SEU_USUARIO/NOME_DO_REPOSITORIO.git)
cd "Projeto 44 - Acesso Remoto"
pip install pyqt5 opencv-python mss pynput numpy