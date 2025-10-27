# 🪟 Guide de Configuration Windows

Ce guide est spécifiquement pour les utilisateurs Windows qui n'ont pas `make` installé.

## 📋 Prérequis

1. ✅ **Python 3.10+** installé
   - Télécharger depuis : https://www.python.org/downloads/
   - **IMPORTANT** : Cocher "Add Python to PATH" lors de l'installation

2. ✅ **Git** installé (Git Bash ou Git for Windows)
   - Télécharger depuis : https://git-scm.com/download/win

3. ✅ **MetaTrader 5** installé
   - Télécharger depuis : https://www.metatrader5.com/

4. ✅ **Compte Deriv** (Demo ou Real)
   - S'inscrire sur : https://deriv.com/

## 🚀 Installation Rapide

### Méthode 1 : Script Batch (Recommandé pour débutants)

1. **Ouvrir Git Bash** dans le dossier du projet

2. **Exécuter le script de setup** :
   ```bash
   ./setup.bat
   ```

3. **Configurer les identifiants MT5** :
   ```bash
   notepad .env
   ```

   Remplir :
   ```
   MT5_LOGIN=votre_numero_compte
   MT5_PASSWORD=votre_mot_de_passe
   MT5_SERVER=Deriv-Demo
   ```

### Méthode 2 : PowerShell (Recommandé pour utilisateurs avancés)

1. **Ouvrir PowerShell** dans le dossier du projet
   - Clic droit dans le dossier → "Ouvrir dans PowerShell"

2. **Autoriser l'exécution de scripts** (une seule fois) :
   ```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   ```

3. **Exécuter le script de setup** :
   ```powershell
   .\setup.ps1
   ```

4. **Configurer les identifiants MT5** :
   ```powershell
   notepad .env
   ```

### Méthode 3 : Installation Manuelle

Si les scripts ne fonctionnent pas, voici les commandes manuelles :

```bash
# 1. Créer les dossiers
mkdir -p data/raw data/processed data/models logs results/plots results/reports

# 2. Créer le fichier .env
cp .env.example .env

# 3. Installer les dépendances
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 4. Éditer .env
notepad .env
```

## 📊 Utilisation

### Commandes Rapides (avec commands.bat)

Utiliser le fichier `commands.bat` pour les opérations courantes :

```bash
# Voir l'aide
commands.bat help

# Installer les dépendances
commands.bat install

# Extraire tous les symboles
commands.bat extract

# Extraire un symbole spécifique
commands.bat extract-symbol

# Analyser les données
commands.bat analyze

# Entraîner un modèle
commands.bat train

# Lancer Jupyter
commands.bat notebook

# Nettoyer les fichiers temporaires
commands.bat clean
```

### Commandes Manuelles Python

Si vous préférez utiliser Python directement :

#### 1. Extraction de données

**Tous les symboles** :
```bash
python src/extractors/mt5_extractor.py --all --days 365
```

**Un symbole spécifique** :
```bash
python src/extractors/mt5_extractor.py --symbol "Volatility 10 Index" --timeframe M1 --days 365
```

**Autres exemples** :
```bash
# Volatility indices
python src/extractors/mt5_extractor.py --symbol "Volatility 25 Index" --timeframe M1 --days 365
python src/extractors/mt5_extractor.py --symbol "Volatility 75 Index" --timeframe M5 --days 180

# Crash/Boom indices
python src/extractors/mt5_extractor.py --symbol "Crash 500 Index" --timeframe M1 --days 365
python src/extractors/mt5_extractor.py --symbol "Boom 500 Index" --timeframe M1 --days 365
```

#### 2. Analyse exploratoire

**Jupyter Notebook** (Recommandé) :
```bash
jupyter notebook notebooks/01_exploratory_analysis.ipynb
```

**Ou en ligne de commande** :
```bash
# Analyse statistique
python src/analyzers/statistical_analyzer.py

# Détection de patterns
python src/analyzers/pattern_detector.py
```

#### 3. Entraînement de modèle

```bash
python src/models/lstm_predictor.py
```

#### 4. Backtesting

```bash
python src/backtesting/backtest_engine.py
```

## 🛠️ Dépannage Windows

### Erreur : "python n'est pas reconnu"

**Solution** :
1. Vérifier que Python est installé : ouvrir cmd et taper `python --version`
2. Si non trouvé, réinstaller Python et **cocher "Add to PATH"**
3. Ou ajouter manuellement Python au PATH :
   - Chercher "Variables d'environnement" dans Windows
   - Ajouter le chemin Python (ex: `C:\Python310\` et `C:\Python310\Scripts\`)

### Erreur : "pip n'est pas reconnu"

**Solution** :
```bash
python -m ensurepip --upgrade
python -m pip install --upgrade pip
```

### Erreur : "No module named 'MetaTrader5'"

**Solution** :
```bash
python -m pip install MetaTrader5
```

### Erreur : MT5 initialization failed

**Solutions** :
1. ✅ Vérifier que MT5 est **ouvert** et **connecté**
2. ✅ Vérifier les identifiants dans `.env`
3. ✅ Vérifier que le serveur est correct (`Deriv-Demo` ou `Deriv-Real`)
4. ✅ Redémarrer MT5

### Erreur : Permission denied (PowerShell)

**Solution** :
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

## 📝 Workflow Complet sur Windows

### 1️⃣ Installation Initiale (une seule fois)

```bash
# Dans Git Bash ou PowerShell
cd ~/Documents/Trading\ Fiacre/AlgoIndicesScrap

# Exécuter le setup
./setup.bat
# ou
.\setup.ps1

# Éditer le fichier .env
notepad .env
```

### 2️⃣ Extraction des Données

```bash
# Extraire Volatility 10
python src/extractors/mt5_extractor.py --symbol "Volatility 10 Index" --timeframe M1 --days 365

# Vérifier que les données sont bien là
dir data\raw
```

### 3️⃣ Analyse dans Jupyter

```bash
# Lancer Jupyter
jupyter notebook notebooks/

# Ouvrir 01_exploratory_analysis.ipynb dans le navigateur
# Exécuter les cellules une par une (Shift + Enter)
```

### 4️⃣ Comprendre les Résultats

Les analyses vont te dire :
- **Hurst < 0.5** → L'indice est **mean-reverting** (retour à la moyenne)
- **Hurst > 0.5** → L'indice est **trending** (suit des tendances)
- **Spikes détectés** → Nombre et timing des spikes Crash/Boom
- **Cycles trouvés** → Périodicités cachées dans les prix

### 5️⃣ Créer une Stratégie

Basé sur les résultats, tu peux :

**Si Mean Reverting (H < 0.5)** :
```python
# Stratégie : acheter quand prix bas, vendre quand prix haut
# Exemple dans notebooks/
```

**Si Trending (H > 0.5)** :
```python
# Stratégie : suivre la tendance
# Exemple dans notebooks/
```

## 🎓 Ressources Windows

### Éditeurs de Code Recommandés

1. **VS Code** (Gratuit, excellent pour Python)
   - Télécharger : https://code.visualstudio.com/
   - Extensions à installer :
     - Python
     - Jupyter
     - GitLens

2. **PyCharm Community** (Gratuit, IDE complet)
   - Télécharger : https://www.jetbrains.com/pycharm/download/

### Outils Supplémentaires

1. **Windows Terminal** (Meilleur que cmd)
   - Installer depuis Microsoft Store

2. **Anaconda** (Alternative pour gérer Python)
   - Télécharger : https://www.anaconda.com/download

## 📋 Checklist de Vérification

Avant de commencer l'analyse, vérifier :

- [ ] Python installé et dans le PATH
- [ ] MT5 installé et compte configuré
- [ ] Dépendances Python installées (`pip list`)
- [ ] Fichier `.env` configuré avec identifiants MT5
- [ ] MT5 ouvert et connecté au serveur
- [ ] Données extraites dans `data/raw/`
- [ ] Jupyter fonctionne (`jupyter notebook`)

## 🆘 Support

Si tu rencontres des problèmes :

1. Vérifier le fichier `logs/extraction.log` pour les erreurs
2. Consulter la documentation MT5 Python
3. Créer une issue sur GitHub avec :
   - Version Python (`python --version`)
   - Version MT5
   - Message d'erreur complet
   - Fichier log

## 📚 Commandes de Référence Rapide

```bash
# Installation
python -m pip install -r requirements.txt

# Extraction
python src/extractors/mt5_extractor.py --symbol "Volatility 10 Index" --timeframe M1 --days 365

# Analyse
jupyter notebook notebooks/01_exploratory_analysis.ipynb

# Training
python src/models/lstm_predictor.py

# Backtest
python src/backtesting/backtest_engine.py

# Nettoyage
commands.bat clean
```

---

**Prêt à décrypter les algorithmes ! 🚀**
