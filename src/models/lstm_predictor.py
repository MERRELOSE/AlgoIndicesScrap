"""
LSTM Predictor - Deep Learning model for time series prediction
"""

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from typing import Tuple, Optional, List
from loguru import logger
from pathlib import Path
import json


class TimeSeriesDataset(Dataset):
    """PyTorch Dataset for time series data"""

    def __init__(
        self,
        data: np.ndarray,
        sequence_length: int,
        prediction_horizon: int = 1
    ):
        """
        Initialize dataset

        Args:
            data: Time series data (n_samples, n_features)
            sequence_length: Length of input sequences
            prediction_horizon: How many steps ahead to predict
        """
        self.data = data
        self.sequence_length = sequence_length
        self.prediction_horizon = prediction_horizon

    def __len__(self):
        return len(self.data) - self.sequence_length - self.prediction_horizon + 1

    def __getitem__(self, idx):
        # Input sequence
        x = self.data[idx:idx + self.sequence_length]

        # Target (next value(s))
        y = self.data[idx + self.sequence_length:idx + self.sequence_length + self.prediction_horizon, 0]

        return torch.FloatTensor(x), torch.FloatTensor(y)


class LSTMModel(nn.Module):
    """LSTM neural network for time series prediction"""

    def __init__(
        self,
        input_size: int,
        hidden_size: int = 128,
        num_layers: int = 2,
        output_size: int = 1,
        dropout: float = 0.2,
        bidirectional: bool = False
    ):
        """
        Initialize LSTM model

        Args:
            input_size: Number of input features
            hidden_size: Hidden layer size
            num_layers: Number of LSTM layers
            output_size: Number of output features
            dropout: Dropout rate
            bidirectional: Whether to use bidirectional LSTM
        """
        super(LSTMModel, self).__init__()

        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.bidirectional = bidirectional
        self.num_directions = 2 if bidirectional else 1

        # LSTM layers
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0,
            batch_first=True,
            bidirectional=bidirectional
        )

        # Fully connected layers
        self.fc = nn.Sequential(
            nn.Linear(hidden_size * self.num_directions, hidden_size // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size // 2, output_size)
        )

    def forward(self, x):
        """Forward pass"""
        batch_size = x.size(0)

        # Initialize hidden state
        h0 = torch.zeros(
            self.num_layers * self.num_directions,
            batch_size,
            self.hidden_size
        ).to(x.device)

        c0 = torch.zeros(
            self.num_layers * self.num_directions,
            batch_size,
            self.hidden_size
        ).to(x.device)

        # LSTM forward
        out, (hn, cn) = self.lstm(x, (h0, c0))

        # Use last output
        out = out[:, -1, :]

        # Fully connected
        out = self.fc(out)

        return out


class LSTMPredictor:
    """Wrapper class for LSTM training and prediction"""

    def __init__(
        self,
        input_size: int = 1,
        hidden_size: int = 128,
        num_layers: int = 2,
        dropout: float = 0.2,
        bidirectional: bool = True,
        sequence_length: int = 60,
        prediction_horizon: int = 1,
        learning_rate: float = 0.001,
        device: str = 'cuda' if torch.cuda.is_available() else 'cpu'
    ):
        """
        Initialize LSTM Predictor

        Args:
            input_size: Number of input features
            hidden_size: Hidden layer size
            num_layers: Number of LSTM layers
            dropout: Dropout rate
            bidirectional: Use bidirectional LSTM
            sequence_length: Length of input sequences
            prediction_horizon: Prediction horizon
            learning_rate: Learning rate
            device: Device to use (cuda/cpu)
        """
        self.sequence_length = sequence_length
        self.prediction_horizon = prediction_horizon
        self.device = device
        self.scaler = StandardScaler()

        # Create model
        self.model = LSTMModel(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            output_size=prediction_horizon,
            dropout=dropout,
            bidirectional=bidirectional
        ).to(device)

        # Optimizer and loss
        self.optimizer = optim.Adam(self.model.parameters(), lr=learning_rate)
        self.criterion = nn.MSELoss()

        # Training history
        self.history = {
            'train_loss': [],
            'val_loss': []
        }

        logger.info(f"LSTM Predictor initialized on {device}")
        logger.info(f"Model parameters: {sum(p.numel() for p in self.model.parameters()):,}")

    def prepare_data(
        self,
        data: pd.DataFrame,
        price_column: str = 'Close',
        feature_columns: Optional[List[str]] = None,
        train_ratio: float = 0.7,
        val_ratio: float = 0.15
    ) -> Tuple[DataLoader, DataLoader, DataLoader]:
        """
        Prepare data for training

        Args:
            data: DataFrame with time series data
            price_column: Column to predict
            feature_columns: Additional feature columns
            train_ratio: Training set ratio
            val_ratio: Validation set ratio

        Returns:
            Tuple of (train_loader, val_loader, test_loader)
        """
        logger.info("Preparing data...")

        # Select features
        if feature_columns is None:
            features = data[[price_column]].values
        else:
            features = data[[price_column] + feature_columns].values

        # Scale data
        features_scaled = self.scaler.fit_transform(features)

        # Split data
        n_samples = len(features_scaled)
        train_size = int(n_samples * train_ratio)
        val_size = int(n_samples * val_ratio)

        train_data = features_scaled[:train_size]
        val_data = features_scaled[train_size:train_size + val_size]
        test_data = features_scaled[train_size + val_size:]

        # Create datasets
        train_dataset = TimeSeriesDataset(
            train_data,
            self.sequence_length,
            self.prediction_horizon
        )
        val_dataset = TimeSeriesDataset(
            val_data,
            self.sequence_length,
            self.prediction_horizon
        )
        test_dataset = TimeSeriesDataset(
            test_data,
            self.sequence_length,
            self.prediction_horizon
        )

        # Create dataloaders
        train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True)
        val_loader = DataLoader(val_dataset, batch_size=64, shuffle=False)
        test_loader = DataLoader(test_dataset, batch_size=64, shuffle=False)

        logger.info(f"Train samples: {len(train_dataset)}")
        logger.info(f"Val samples: {len(val_dataset)}")
        logger.info(f"Test samples: {len(test_dataset)}")

        return train_loader, val_loader, test_loader

    def train_epoch(self, train_loader: DataLoader) -> float:
        """Train for one epoch"""
        self.model.train()
        total_loss = 0

        for batch_x, batch_y in train_loader:
            batch_x = batch_x.to(self.device)
            batch_y = batch_y.to(self.device)

            # Forward pass
            outputs = self.model(batch_x)

            # Calculate loss
            if self.prediction_horizon == 1:
                outputs = outputs.squeeze()
            loss = self.criterion(outputs, batch_y)

            # Backward pass
            self.optimizer.zero_grad()
            loss.backward()
            self.optimizer.step()

            total_loss += loss.item()

        return total_loss / len(train_loader)

    def validate(self, val_loader: DataLoader) -> float:
        """Validate the model"""
        self.model.eval()
        total_loss = 0

        with torch.no_grad():
            for batch_x, batch_y in val_loader:
                batch_x = batch_x.to(self.device)
                batch_y = batch_y.to(self.device)

                # Forward pass
                outputs = self.model(batch_x)

                # Calculate loss
                if self.prediction_horizon == 1:
                    outputs = outputs.squeeze()
                loss = self.criterion(outputs, batch_y)

                total_loss += loss.item()

        return total_loss / len(val_loader)

    def train(
        self,
        train_loader: DataLoader,
        val_loader: DataLoader,
        epochs: int = 100,
        early_stopping_patience: int = 10,
        save_path: Optional[str] = None
    ):
        """
        Train the model

        Args:
            train_loader: Training data loader
            val_loader: Validation data loader
            epochs: Number of epochs
            early_stopping_patience: Patience for early stopping
            save_path: Path to save best model
        """
        logger.info(f"Training for {epochs} epochs...")

        best_val_loss = float('inf')
        patience_counter = 0

        for epoch in range(epochs):
            # Train
            train_loss = self.train_epoch(train_loader)

            # Validate
            val_loss = self.validate(val_loader)

            # Save history
            self.history['train_loss'].append(train_loss)
            self.history['val_loss'].append(val_loss)

            # Print progress
            if (epoch + 1) % 10 == 0:
                logger.info(
                    f"Epoch {epoch+1}/{epochs} - "
                    f"Train Loss: {train_loss:.6f}, Val Loss: {val_loss:.6f}"
                )

            # Early stopping
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                patience_counter = 0

                # Save best model
                if save_path:
                    self.save_model(save_path)
                    logger.info(f"Model saved at epoch {epoch+1}")
            else:
                patience_counter += 1

            if patience_counter >= early_stopping_patience:
                logger.info(f"Early stopping at epoch {epoch+1}")
                break

        logger.info(f"Training complete! Best val loss: {best_val_loss:.6f}")

    def predict(self, data: np.ndarray) -> np.ndarray:
        """
        Make predictions

        Args:
            data: Input data (sequence_length, n_features)

        Returns:
            Predictions
        """
        self.model.eval()

        with torch.no_grad():
            # Scale input
            data_scaled = self.scaler.transform(data)

            # Convert to tensor
            x = torch.FloatTensor(data_scaled).unsqueeze(0).to(self.device)

            # Predict
            output = self.model(x)

            # Inverse transform
            prediction = output.cpu().numpy()

            # Inverse scale (only for price column)
            dummy = np.zeros((1, self.scaler.n_features_in_))
            dummy[0, 0] = prediction[0]
            prediction_unscaled = self.scaler.inverse_transform(dummy)[0, 0]

            return prediction_unscaled

    def predict_sequence(
        self,
        initial_sequence: np.ndarray,
        n_steps: int
    ) -> np.ndarray:
        """
        Predict multiple steps ahead

        Args:
            initial_sequence: Initial sequence (sequence_length, n_features)
            n_steps: Number of steps to predict

        Returns:
            Predictions array
        """
        predictions = []
        current_sequence = initial_sequence.copy()

        for _ in range(n_steps):
            # Predict next step
            pred = self.predict(current_sequence)
            predictions.append(pred)

            # Update sequence
            new_row = np.zeros((1, current_sequence.shape[1]))
            new_row[0, 0] = pred

            # Roll sequence
            current_sequence = np.vstack([current_sequence[1:], new_row])

        return np.array(predictions)

    def evaluate(self, test_loader: DataLoader) -> Dict:
        """
        Evaluate the model

        Args:
            test_loader: Test data loader

        Returns:
            Dictionary with evaluation metrics
        """
        logger.info("Evaluating model...")

        self.model.eval()
        predictions = []
        actuals = []

        with torch.no_grad():
            for batch_x, batch_y in test_loader:
                batch_x = batch_x.to(self.device)

                # Predict
                outputs = self.model(batch_x)

                # Store predictions and actuals
                if self.prediction_horizon == 1:
                    outputs = outputs.squeeze()

                predictions.extend(outputs.cpu().numpy())
                actuals.extend(batch_y.numpy())

        predictions = np.array(predictions)
        actuals = np.array(actuals)

        # Calculate metrics
        mse = np.mean((predictions - actuals) ** 2)
        rmse = np.sqrt(mse)
        mae = np.mean(np.abs(predictions - actuals))

        # Directional accuracy
        direction_pred = np.diff(predictions) > 0
        direction_actual = np.diff(actuals) > 0
        directional_accuracy = np.mean(direction_pred == direction_actual)

        results = {
            'mse': float(mse),
            'rmse': float(rmse),
            'mae': float(mae),
            'directional_accuracy': float(directional_accuracy),
            'num_samples': len(predictions)
        }

        logger.info(f"Evaluation results: RMSE={rmse:.6f}, MAE={mae:.6f}, "
                   f"Directional Accuracy={directional_accuracy:.4f}")

        return results

    def save_model(self, path: str):
        """Save model to disk"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Save model state
        torch.save({
            'model_state_dict': self.model.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'history': self.history,
            'scaler': self.scaler
        }, path)

        # Save config
        config = {
            'sequence_length': self.sequence_length,
            'prediction_horizon': self.prediction_horizon,
            'device': self.device
        }

        config_path = path.parent / f"{path.stem}_config.json"
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)

        logger.info(f"Model saved to {path}")

    def load_model(self, path: str):
        """Load model from disk"""
        checkpoint = torch.load(path, map_location=self.device)

        self.model.load_state_dict(checkpoint['model_state_dict'])
        self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        self.history = checkpoint['history']
        self.scaler = checkpoint['scaler']

        logger.info(f"Model loaded from {path}")


def main():
    """Example usage"""
    # Load data
    data = pd.read_parquet("data/raw/Volatility_10_Index_M1.parquet")

    # Create predictor
    predictor = LSTMPredictor(
        input_size=1,
        hidden_size=128,
        num_layers=2,
        sequence_length=60,
        prediction_horizon=1
    )

    # Prepare data
    train_loader, val_loader, test_loader = predictor.prepare_data(
        data,
        price_column='Close'
    )

    # Train
    predictor.train(
        train_loader,
        val_loader,
        epochs=100,
        early_stopping_patience=10,
        save_path="data/models/lstm_model.pth"
    )

    # Evaluate
    results = predictor.evaluate(test_loader)
    print("\n=== EVALUATION RESULTS ===")
    print(f"RMSE: {results['rmse']:.6f}")
    print(f"MAE: {results['mae']:.6f}")
    print(f"Directional Accuracy: {results['directional_accuracy']:.4f}")


if __name__ == "__main__":
    main()
