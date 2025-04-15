import os
import re
import logging
import time
import numpy as np
import cv2
from datetime import datetime
from PIL import Image
import face_recognition
import easyocr
import sys


# ===== VERIFICAÇÃO DE VERSÕES =====
def check_versions():
    required_versions = {
        'numpy': '1.26.4',
        'face-recognition': '1.2.3'
    }

    current_versions = {
        'numpy': np.__version__,
        'face-recognition': face_recognition.__version__
    }

    for lib, version in required_versions.items():
        if current_versions[lib] != version:
            raise ImportError(
                f"Versão incompatível de {lib} detectada: {current_versions[lib]}\n"
                f"Requisito: {version}\n"
                f"Execute: pip install {lib}=={version}"
            )


check_versions()  # Verifica imediatamente ao importar

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('reconhecimento.log'),
        logging.StreamHandler()
    ]
)
# ===== CONFIGURAÇÃO INICIAL =====
logger = logging.getLogger(__name__)

# Directory configurations
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# BASE_DIR = r"C:\condominio"

DIR_ROSTOS = os.path.join(BASE_DIR, "static", "rostos_moradores")
DIR_PLACAS = os.path.join(BASE_DIR, "static", "placas_moradores")
TEMP_DIR = os.path.join(BASE_DIR, "static", "temp")

# Create directories if they don't exist
os.makedirs(DIR_ROSTOS, exist_ok=True)
os.makedirs(DIR_PLACAS, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)


class FaceRecognitionSystem:
    def __init__(self):
        self._validate_environment()
        self.known_face_encodings = []
        self.known_face_ids = []
        self.load_known_faces()

    def _validate_environment(self):
        """Verifica requisitos do sistema"""
        try:
            # Teste básico de funcionamento
            test_image = np.zeros((100, 100, 3), dtype=np.uint8)
            face_recognition.face_encodings(test_image)
        except Exception as e:
            logger.error("Configuração do ambiente falhou: %s", str(e))
            raise


class ImageProcessor:
    @staticmethod
    def ensure_rgb(image):
        """Convert image to 8-bit RGB format"""
        if image is None:
            return None

        # If grayscale (2D array)
        if len(image.shape) == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)

        # If RGBA (4 channels)
        if image.shape[2] == 4:
            return cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)

        # If already RGB but not 8-bit
        if image.dtype != np.uint8:
            return (image * 255).astype(np.uint8)

        return image


class ImageValidator:
    @staticmethod
    def convert_to_rgb(image):
        """Convert any image format to 8-bit RGB"""
        if image is None:
            return None
        if len(image.shape) == 2:  # Grayscale
            return cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
        if image.shape[2] == 4:    # RGBA
            return cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)
        return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    def validate_image(image):
        """Ensure image is valid 8-bit RGB numpy array"""
        if not isinstance(image, np.ndarray):
            return False
        if image.dtype != np.uint8:
            return False
        if len(image.shape) != 3 or image.shape[2] != 3:
            return False
        return True


class ReconhecimentoFacial:
    def __init__(self):
        self.known_face_encodings = []
        self.known_face_ids = []
        # Load faces on initialization
        self._carregar_rostos_conhecidos(DIR_ROSTOS)

    def _carregar_rostos_conhecidos(self, diretorio):
        """Carrega rostos conhecidos do diretório especificado"""
        self.known_face_encodings = []
        self.known_face_ids = []

        try:
            for filename in os.listdir(diretorio):
                if filename.startswith('morador_') and filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                    caminho = os.path.join(diretorio, filename)
                    id_morador = int(filename.split('_')[1].split('.')[0])

                    # Carrega a imagem
                    imagem = face_recognition.load_image_file(caminho)
                    encodings = face_recognition.face_encodings(imagem)

                    if encodings:
                        self.known_face_encodings.append(encodings[0])
                        self.known_face_ids.append(id_morador)
                        logger.info(f"Rosto carregado: {filename} (ID: {id_morador})")
                    else:
                        logger.warning(f"Nenhum rosto detectado em: {filename}")

            logger.info(f"Total de rostos carregados: {len(self.known_face_ids)}")

        except Exception as e:
            logger.error(f"Erro ao carregar rostos conhecidos: {str(e)}")
            raise

    def verificar_rosto(self, imagem_bytes):
        """Verifica se a imagem contém um rosto conhecido"""
        try:
            # Converte bytes para imagem
            nparr = np.frombuffer(imagem_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            
            # Encontra rostos na imagem
            face_locations = face_recognition.face_locations(rgb_img)
            face_encodings = face_recognition.face_encodings(rgb_img, face_locations)
            
            if not face_encodings:
                return None
                
            # Compara com rostos conhecidos
            for face_encoding in face_encodings:
                matches = face_recognition.compare_faces(self.known_face_encodings, face_encoding)
                if True in matches:
                    first_match_index = matches.index(True)
                    return self.known_face_ids[first_match_index]
                    
            return None
            
        except Exception as e:
            logger.error(f"Erro no reconhecimento facial: {str(e)}")
            raise

    def load_known_faces(self):
        """Carrega rostos conhecidos com tratamento robusto"""
        logger.info("Carregando rostos conhecidos...")
        self.known_face_encodings = []
        self.known_face_ids = []

        try:
            for filename in os.listdir(DIR_ROSTOS):
                try:
                    # Use DIR_ROSTOS instead of hardcoded path
                    image_path = os.path.join(DIR_ROSTOS, filename)

                    # Skip non-image files
                    if not filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                        continue

                    # Carrega com PIL primeiro para melhor compatibilidade
                    pil_image = Image.open(image_path)
                    if pil_image.mode != 'RGB':
                        pil_image = pil_image.convert('RGB')

                    image = np.array(pil_image)

                    # Conversão explícita para uint8
                    if image.dtype != np.uint8:
                        image = image.astype(np.uint8)

                    # Verificação final do formato
                    if len(image.shape) != 3 or image.shape[2] != 3:
                        raise ValueError("Formato de imagem inválido")

                    encodings = face_recognition.face_encodings(image)
                    if encodings:
                        self.known_face_encodings.append(encodings[0])
                        self.known_face_ids.append(filename.split('.')[0])
                        logger.info("Rosto carregado: %s", filename)

                except Exception as e:
                    logger.warning("Falha ao processar %s: %s",
                                   filename, str(e))

        except Exception as e:
            logger.error(f"Erro ao acessar diretório de rostos: {str(e)}")

    def _load_image_file(self, path):
        """Load image with format validation"""
        try:
            # First try with PIL which handles more formats
            pil_image = Image.open(path)
            if pil_image.mode != 'RGB':
                pil_image = pil_image.convert('RGB')

            img_array = np.array(pil_image)
            rgb_img = ImageValidator.convert_to_rgb(img_array)

            if not ImageValidator.validate_image(rgb_img):
                logger.error(f"Invalid image format: {path}")
                return None

            return rgb_img

        except Exception as e:
            logger.error(f"Failed to load {path}: {str(e)}")
            return None

    def processar_imagem(self, imagem_bytes):
        """Process image with comprehensive validation"""
        try:
            if not imagem_bytes:
                raise ValueError("Empty image data")

            img = self._decode_image(imagem_bytes)
            if img is None:
                return None

            return self._recognize_faces(img)

        except Exception as e:
            logger.error(f"Processing error: {str(e)}")
            return None

    def _decode_image(self, image_bytes: bytes) -> np.ndarray:
        """Decode image bytes with validation"""
        try:
            if not isinstance(image_bytes, (bytes, bytearray)):
                logger.error("Invalid image bytes type: %s", type(image_bytes))
                return None

            # Convert bytes to numpy array
            nparr = np.frombuffer(image_bytes, dtype=np.uint8)

            # Decode image using OpenCV
            img = cv2.imdecode(nparr, flags=cv2.IMREAD_UNCHANGED)

            if img is None:
                logger.error("Failed to decode image from bytes")
                return None

            # Convert to RGB format
            rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

            # Validate image format
            if not ImageValidator.validate_image(rgb_img):
                logger.error("Invalid image format after conversion")
                return None

            return rgb_img
        except Exception as e:
            logger.error("Image decoding failed: %s", str(e))
            return None

    def _recognize_faces(self, img):
        """Perform face recognition on validated image"""
        try:
            face_locations = face_recognition.face_locations(
                img,
                number_of_times_to_upsample=1,
                model=self.face_detection_model
            )

            if not face_locations:
                logger.warning("No faces detected")
                return None

            face_encodings = face_recognition.face_encodings(
                img, face_locations)
            results = []

            for i, encoding in enumerate(face_encodings):
                match = self._find_match(encoding)
                if match:
                    results.append({
                        'id': match['id'],
                        'confidence': match['confidence'],
                        'location': face_locations[i]
                    })

            return results if results else None

        except Exception as e:
            logger.error(f"Recognition error: {str(e)}")
            return None

    def _find_match(self, encoding):
        """Find best matching face"""
        try:
            # Compare input encoding with known faces
            matches = face_recognition.compare_faces(
                self.known_face_encodings,
                encoding,
                tolerance=self.min_confidence
            )

            if True not in matches:
                return None

            # Calculate face distances
            distances = face_recognition.face_distance(
                self.known_face_encodings,
                encoding
            )
            best_idx = np.argmin(distances)
            confidence = 1 - distances[best_idx]

            if confidence >= self.min_confidence:
                return {
                    'id': self.known_face_ids[best_idx],
                    'confidence': confidence
                }
            return None

        except Exception as e:
            logger.error(f"Matching error: {str(e)}")
            return None

    def adicionar_rosto(self, morador_id, imagem_bytes):
        """Add new face with validation"""
        try:
            img = self._decode_image(imagem_bytes)
            if img is None:
                return False

            filename = f"morador_{morador_id}.jpg"
            path = os.path.join(DIR_ROSTOS, filename)

            # Save using PIL for consistent format
            Image.fromarray(img).save(path, quality=95)
            self.load_known_faces()
            return True

        except Exception as e:
            logger.error(f"Error adding face: {str(e)}")
            return False


class ReconhecimentoPlacas:
    def __init__(self):
        try:
            # Configurações do EasyOCR
            self.reader = easyocr.Reader(
                ['pt'],
                gpu=False,
                model_storage_directory='models',
                download_enabled=True
            )

            # Configurações do detector de placas baseado no tutorial
            self._initialize_plate_detector()
            
            # Padrões e configurações existentes
            self.padroes_placas = [
                r'^[A-Z]{3}\d[A-Z]\d{2}$',  # Modelo Mercosul (ABC1D23)
                r'^[A-Z]{3}\d{4}$'           # Modelo antigo (ABC1234)
            ]
            self.correcoes_ocr = {
                '0': 'O', '1': 'I', '2': 'Z', '4': 'A',
                '5': 'S', '6': 'G', '8': 'B', ' ': ''
            }

            logger.info("Reconhecedor de placas inicializado com sucesso")

        except Exception as e:
            logger.error(f"Falha na inicialização do ReconhecimentoPlacas: {str(e)}")
            raise
    
    def _initialize_plate_detector(self):
        """Inicializa o detector de placas baseado em Haar Cascade"""
        # Caminho para o classificador cascade (usando o mesmo do tutorial)
        cascade_path = os.path.join(
            cv2.data.haarcascades,
            'haarcascade_russian_plate_number.xml'
        )

        # Verificar se o arquivo existe
        if not os.path.exists(cascade_path):
            raise FileNotFoundError(f"Arquivo do classificador cascade não encontrado: {cascade_path}")

        # Carregar o classificador
        self.plate_cascade = cv2.CascadeClassifier(cascade_path)
        
        # Verificar se foi carregado corretamente
        if self.plate_cascade.empty():
            raise RuntimeError("Falha ao carregar o classificador cascade")

        # Parâmetros otimizados baseados no tutorial
        self.detection_params = {
            'scaleFactor': 1.05,  # Fator de redução (1.05-1.4)
            'minNeighbors': 5,    # Número de vizinhos (3-6)
            'minSize': (100, 30), # Tamanho mínimo da placa
            'maxSize': (400, 100) # Tamanho máximo da placa
        }
        
    def _detectar_placa(self, img):
        """Localiza a região da placa na imagem"""
        try:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            plates = self.plate_cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(100, 30),
                maxSize=(400, 100)
            )

            if len(plates) > 0:
                x, y, w, h = plates[0]
                return img[y:y+h, x:x+w]
            return None
        except Exception as e:
            logger.error(f"Erro na detecção de placa: {str(e)}")
            return None

    def reconhecer_de_imagem(self, imagem_bytes):
        """
        Reconhece uma placa de veículo a partir de uma imagem
        Retorna a placa formatada se reconhecida, None caso contrário
        """
        try:
            # Decodificar imagem
            img = self._bytes_para_imagem(imagem_bytes)
            if img is None:
                raise ValueError("Imagem inválida")

            # 1. Detectar região da placa
            placa_img = self._detectar_placa(img)
            if placa_img is None:  # Se não detectar placa, usar imagem inteira
                placa_img = img

            # 2. Pré-processamento avançado
            processed = self._preprocessar_placa(placa_img)

            # 3. Executar OCR
            resultados = self._executar_ocr(processed)

            # 4. Processar e validar resultados
            placa = self._processar_resultados_ocr(resultados)

            if placa:
                logger.info(f"Placa reconhecida: {placa}")
                return placa

            logger.warning("Nenhuma placa válida encontrada")
            return None

        except Exception as e:
            logger.error(f"Erro no reconhecimento de placa: {str(e)}", exc_info=True)
            return None

    def _preprocessar_placa(self, img):
        """Pré-processamento avançado da região da placa"""
        # Redimensionar para tamanho consistente (baseado no tutorial)
        img = cv2.resize(img, (400, 100))
        
        # Converter para tons de cinza
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Aplicar filtro bilateral para redução de ruído
        gray = cv2.bilateralFilter(gray, 11, 17, 17)
        
        # Limiarização adaptativa
        thresh = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 11, 2
        )
        
        # Operações morfológicas para remover ruídos
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        processed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        
        return processed    
            

    def _bytes_para_imagem(self, imagem_bytes):
        """Converte bytes para imagem OpenCV"""
        return cv2.imdecode(np.frombuffer(imagem_bytes, np.uint8), cv2.IMREAD_COLOR)


    def _preprocessar_placa(self, img):
        """Aplica técnicas avançadas de pré-processamento"""
        # Converter para escala de cinza
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Equalização de histograma adaptativa
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        equalized = clahe.apply(gray)

        # Redução de ruído
        filtered = cv2.bilateralFilter(equalized, 11, 17, 17)

        # Binarização adaptativa
        thresh = cv2.adaptiveThreshold(
            filtered, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )

        # Operações morfológicas
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        processed = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

        return processed

    def _executar_ocr(self, img):
        """Executa o OCR na imagem pré-processada"""
        return self.reader.readtext(
            img,
            decoder='beamsearch',
            beamWidth=5,
            batch_size=1,
            workers=0,
            allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
            detail=1
        )

    def _processar_resultados_ocr(self, resultados):
        """Processa e valida os resultados do OCR"""
        # Ordenar por confiança (maior primeiro)
        for (_, texto, confianca) in sorted(resultados, key=lambda x: -x[2]):
            if confianca < 0.4:  # Ignorar resultados com baixa confiança
                continue

            # Aplicar correções de OCR
            texto_corrigido = self._corrigir_ocr(texto.upper())

            # Normalizar formato da placa
            placa = self._normalizar_placa(texto_corrigido)

            # Validar placa
            if placa and self._validar_placa(placa):
                return placa

        return None

    def _corrigir_ocr(self, texto):
        """Corrige erros comuns de OCR"""
        return ''.join([self.correcoes_ocr.get(c, c) for c in texto])

    def _normalizar_placa(self, texto):
        """Normaliza o texto para o formato padrão de placa"""
        texto = re.sub(r'[^A-Z0-9]', '', texto.upper())

        # Verificar padrões e formatar
        for padrao in self.padroes_placas:
            if re.match(padrao, texto):
                return f"{texto[:3]}-{texto[3:]}"

        return None

    def _validar_placa(self, placa):
        """Validação adicional da placa"""
        # Remover formatação para validação
        placa_sem_formatacao = placa.replace('-', '')

        # Verificar formato
        if not (re.match(r'^[A-Z]{3}\d[A-Z]\d{2}$', placa_sem_formatacao) or
                re.match(r'^[A-Z]{3}\d{4}$', placa_sem_formatacao)):
            return False

        # Verificação adicional para placas antigas
        if len(placa_sem_formatacao) == 7:  # Modelo antigo
            numeros = placa_sem_formatacao[3:]
            if numeros == numeros[0] * len(numeros):  # Sequência repetida
                return False

        return True


class GerenciadorAcesso:
    def __init__(self, reconhecimento_facial, reconhecimento_placas):
        self.reconhecimento_facial = reconhecimento_facial
        self.reconhecimento_placas = reconhecimento_placas
        self._verificar_inicializacao()


    def _verificar_inicializacao(self):
        """Verifica se os sistemas estão prontos"""
        try:
            # Verificar reconhecimento facial
            if not self.reconhecimento_facial or not hasattr(self.reconhecimento_facial, 'verificar_rosto'):
                raise RuntimeError("Sistema de reconhecimento facial não inicializado")
            
            # Verificar reconhecimento de placas
            if not self.reconhecimento_placas or not hasattr(self.reconhecimento_placas, 'reconhecer_de_imagem'):
                raise RuntimeError("Sistema de reconhecimento de placas não inicializado")
            
            # Verificar componentes internos do reconhecedor de placas
            if hasattr(self.reconhecimento_placas, '_verificar_inicializacao'):
                if not self.reconhecimento_placas._verificar_inicializacao():
                    raise RuntimeError("Componentes do reconhecedor de placas não inicializados corretamente")
            
            logger.info("Todos os sistemas foram inicializados com sucesso")
            return True
            
        except Exception as e:
            logger.error(f"Erro na verificação de inicialização: {str(e)}")
            raise

    def verificar_entrada(self, imagem_bytes, tipo):
        """Verifica uma tentativa de entrada com tratamento robusto de erros"""
        try:
            # Verificação redundante para garantir que os sistemas estão prontos
            self._verificar_inicializacao()

            if tipo == 'facial':
                resultado = self._verificar_facial(imagem_bytes)
            elif tipo == 'placa':
                resultado = self._verificar_placa(imagem_bytes)
            else:
                raise ValueError(f"Tipo de verificação inválido: {tipo}")

            return resultado

        except Exception as e:
            logger.error(f"Erro na verificação: {str(e)}")
            return {
                'status': 'erro',
                'mensagem': str(e),
                'tipo': tipo
            }
            
    def _verificar_facial(self, imagem_bytes):
        """Lógica específica para reconhecimento facial"""
        try:
            id_morador = self.reconhecimento_facial.verificar_rosto(imagem_bytes)
            if id_morador:
                return {
                    'status': 'liberado',
                    'tipo': 'facial',
                    'id_morador': id_morador,
                    'mensagem': 'Reconhecimento facial bem-sucedido',
                    'timestamp': datetime.now().isoformat()
                }
            return {
                'status': 'negado',
                'tipo': 'facial',
                'mensagem': 'Rosto não reconhecido',
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Erro no reconhecimento facial: {str(e)}")
            raise

    def _verificar_placa(self, imagem_bytes):
        """Lógica específica para reconhecimento de placas"""
        try:
            placa = self.reconhecimento_placas.reconhecer_de_imagem(imagem_bytes)
            if placa:
                return {
                    'status': 'liberado',
                    'tipo': 'placa',
                    'placa': placa,
                    'mensagem': 'Placa reconhecida com sucesso',
                    'timestamp': datetime.now().isoformat()
                }
            return {
                'status': 'negado',
                'tipo': 'placa',
                'mensagem': 'Placa não reconhecida',
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Erro no reconhecimento de placa: {str(e)}")
            raise

# Funções auxiliares para compatibilidade


def reconhecer_rosto(imagem_path):
    """Função legada para reconhecimento facial a partir de arquivo"""
    rf = ReconhecimentoFacial()
    try:
        with open(imagem_path, 'rb') as f:
            imagem_bytes = f.read()
        return rf.processar_imagem(imagem_bytes)
    except Exception as e:
        logger.error(f"Erro no reconhecimento facial (legado): {str(e)}")
        return None


def reconhecer_placa(imagem_path):
    """Função legada para reconhecimento de placa a partir de arquivo"""
    rp = ReconhecimentoPlacas()
    try:
        with open(imagem_path, 'rb') as f:
            imagem_bytes = f.read()
        return rp.reconhecer_de_imagem(imagem_bytes)
    except Exception as e:
        logger.error(f"Erro no reconhecimento de placa (legado): {str(e)}")
        return None


def capturar_imagem(nome_arquivo="captura.jpg"):
    """Captura uma imagem da webcam e salva no disco"""
    try:
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            raise RuntimeError("Não foi possível acessar a webcam")

        # Configurar resolução
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        # Capturar vários frames para estabilizar
        for _ in range(5):
            cap.read()

        ret, frame = cap.read()
        if not ret:
            raise RuntimeError("Falha ao capturar frame da webcam")

        # Salvar imagem
        caminho = os.path.join(TEMP_DIR, nome_arquivo)
        cv2.imwrite(caminho, frame)

        logger.info(f"Imagem capturada e salva como {caminho}")
        return caminho

    except Exception as e:
        logger.error(f"Erro na captura: {str(e)}")
        return None
    finally:
        if 'cap' in locals():
            cap.release()


if __name__ == "__main__":
    print("Testing plate recognition...")
    rp = ReconhecimentoPlacas()
    test_image = "path_to_test_plate_image.jpg"
    if os.path.exists(test_image):
        with open(test_image, 'rb') as f:
            img_bytes = f.read()
        print("Plate recognition result:", rp.reconhecer_de_imagem(img_bytes))
    else:
        print("Test image not found")