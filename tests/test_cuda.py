"""Tests for CUDA detection and image selection functionality."""

from __future__ import annotations

from unittest.mock import patch
import pytest

from airpods.cuda import (
    CUDA_COMPATIBILITY_MAP,
    COMFYUI_IMAGES,
    DEFAULT_CUDA_VERSION,
    select_cuda_version,
    select_comfyui_image,
    get_cuda_info_display,
    _cuda_version_newer,
)
from airpods.system import detect_cuda_compute_capability


class TestSelectCudaVersion:
    """Tests for select_cuda_version function."""

    def test_direct_lookup_success(self):
        """Test direct lookup of compute capabilities in the map."""
        # Test known mappings
        assert select_cuda_version((7, 5)) == "cu126"  # Turing
        assert select_cuda_version((8, 6)) == "cu128"  # Ampere
        assert select_cuda_version((9, 0)) == "cu130"  # Hopper

    def test_none_input_returns_default(self):
        """Test that None input returns default CUDA version."""
        assert select_cuda_version(None) == DEFAULT_CUDA_VERSION

    def test_fallback_to_compatible_version(self):
        """Test fallback logic for unmapped compute capabilities."""
        # Test a capability not in the map but should work with a compatible version
        # For example, 8.7 isn't directly mapped but should work with cu128 (ampere family)
        result = select_cuda_version((8, 7))
        assert result == "cu128"  # Should find cu128 as compatible

    def test_old_gpu_fallback(self):
        """Test very old GPU falls back to default."""
        # Compute 3.0 or older isn't supported by modern CUDA
        result = select_cuda_version((3, 0))
        assert result == DEFAULT_CUDA_VERSION

    def test_future_gpu_gets_latest(self):
        """Test that future GPU architectures get latest CUDA version."""
        result = select_cuda_version((10, 0))  # Future architecture
        # Should get the highest available CUDA version
        assert result in ["cu130", "cu128", DEFAULT_CUDA_VERSION]


class TestSelectComfyuiImage:
    """Tests for select_comfyui_image function."""

    def test_force_cpu_returns_cpu_image(self):
        """Test that force_cpu=True returns CPU image regardless of CUDA version."""
        assert select_comfyui_image("cu128", force_cpu=True) == COMFYUI_IMAGES["cpu"]
        assert select_comfyui_image("cu126", force_cpu=True) == COMFYUI_IMAGES["cpu"]
        assert select_comfyui_image(None, force_cpu=True) == COMFYUI_IMAGES["cpu"]

    def test_none_cuda_version_uses_default(self):
        """Test that None CUDA version uses default."""
        result = select_comfyui_image(None)
        expected = COMFYUI_IMAGES[DEFAULT_CUDA_VERSION]
        assert result == expected

    def test_valid_cuda_versions(self):
        """Test that valid CUDA versions return correct images."""
        assert select_comfyui_image("cu126") == COMFYUI_IMAGES["cu126"]
        assert select_comfyui_image("cu128") == COMFYUI_IMAGES["cu128"]
        assert select_comfyui_image("cu130") == COMFYUI_IMAGES["cu130"]

    def test_unknown_cuda_version_fallback(self):
        """Test that unknown CUDA versions fall back to default."""
        result = select_comfyui_image("cu999")  # Non-existent version
        expected = COMFYUI_IMAGES[DEFAULT_CUDA_VERSION]
        assert result == expected


class TestGetCudaInfoDisplay:
    """Tests for get_cuda_info_display function."""

    def test_no_gpu_display(self):
        """Test display when no GPU is detected."""
        result = get_cuda_info_display(False, "nvidia-smi not found", None, "cu126")
        assert "not available" in result
        assert "nvidia-smi not found" in result

    def test_gpu_without_compute_cap(self):
        """Test display when GPU detected but compute capability unknown."""
        result = get_cuda_info_display(True, "NVIDIA GPU", None, "cu126")
        assert "selected cu126" in result
        assert "compute capability unknown" in result

    def test_successful_detection(self):
        """Test display with successful GPU and compute capability detection."""
        result = get_cuda_info_display(True, "NVIDIA GTX 1650", (7, 5), "cu126")
        assert "CUDA 12.6 (cu126)" in result
        assert "compute 7.5" in result

    def test_all_cuda_versions_display_correctly(self):
        """Test that all CUDA versions have proper display names."""
        test_cases = [
            ("cu118", "CUDA 11.8"),
            ("cu126", "CUDA 12.6"),
            ("cu128", "CUDA 12.8"),
            ("cu130", "CUDA 13.0"),
        ]

        for cuda_ver, expected_display in test_cases:
            result = get_cuda_info_display(True, "Test GPU", (8, 6), cuda_ver)
            assert expected_display in result
            assert cuda_ver in result


class TestCudaVersionNewer:
    """Tests for _cuda_version_newer helper function."""

    def test_newer_version_comparison(self):
        """Test that newer CUDA versions are correctly identified."""
        assert _cuda_version_newer("cu128", "cu126") is True
        assert _cuda_version_newer("cu130", "cu128") is True
        assert _cuda_version_newer("cu126", "cu118") is True

    def test_older_version_comparison(self):
        """Test that older CUDA versions return False."""
        assert _cuda_version_newer("cu126", "cu128") is False
        assert _cuda_version_newer("cu118", "cu126") is False

    def test_same_version_comparison(self):
        """Test that same versions return False."""
        assert _cuda_version_newer("cu128", "cu128") is False

    def test_invalid_version_handling(self):
        """Test handling of invalid version strings."""
        assert _cuda_version_newer("invalid", "cu128") is False
        assert (
            _cuda_version_newer("cu128", "invalid") is True
        )  # "invalid" becomes 0, so cu128 > 0
        assert _cuda_version_newer("invalid", "invalid") is False


class TestDetectCudaComputeCapability:
    """Tests for detect_cuda_compute_capability function."""

    @patch("airpods.system.shutil.which")
    def test_nvidia_smi_not_found(self, mock_which):
        """Test behavior when nvidia-smi is not available."""
        mock_which.return_value = None

        has_gpu, gpu_name, compute_cap = detect_cuda_compute_capability()

        assert has_gpu is False
        assert gpu_name == "nvidia-smi not found"
        assert compute_cap is None

    @patch("airpods.system._run_command")
    @patch("airpods.system.shutil.which")
    def test_nvidia_smi_command_fails(self, mock_which, mock_run_command):
        """Test behavior when nvidia-smi command fails."""
        mock_which.return_value = "/usr/bin/nvidia-smi"
        mock_run_command.return_value = (False, "No devices were found")

        has_gpu, gpu_name, compute_cap = detect_cuda_compute_capability()

        assert has_gpu is False
        assert gpu_name == "nvidia-smi failed"
        assert compute_cap is None

    @patch("airpods.system._run_command")
    @patch("airpods.system.shutil.which")
    def test_no_gpus_detected(self, mock_which, mock_run_command):
        """Test behavior when nvidia-smi runs but finds no GPUs."""
        mock_which.return_value = "/usr/bin/nvidia-smi"
        mock_run_command.return_value = (True, "")

        has_gpu, gpu_name, compute_cap = detect_cuda_compute_capability()

        assert has_gpu is False
        assert gpu_name == "no GPUs detected"
        assert compute_cap is None

    @patch("airpods.system._run_command")
    @patch("airpods.system.shutil.which")
    def test_successful_detection(self, mock_which, mock_run_command):
        """Test successful GPU detection and compute capability parsing."""
        mock_which.return_value = "/usr/bin/nvidia-smi"
        mock_run_command.return_value = (True, "NVIDIA GeForce GTX 1650, 7.5")

        has_gpu, gpu_name, compute_cap = detect_cuda_compute_capability()

        assert has_gpu is True
        assert gpu_name == "NVIDIA GeForce GTX 1650"
        assert compute_cap == (7, 5)

    @patch("airpods.system._run_command")
    @patch("airpods.system.shutil.which")
    def test_multiple_gpus_uses_first(self, mock_which, mock_run_command):
        """Test that detection uses first GPU when multiple are present."""
        mock_which.return_value = "/usr/bin/nvidia-smi"
        mock_run_command.return_value = (
            True,
            "NVIDIA RTX 4090, 8.9\nNVIDIA GTX 1650, 7.5",
        )

        has_gpu, gpu_name, compute_cap = detect_cuda_compute_capability()

        assert has_gpu is True
        assert gpu_name == "NVIDIA RTX 4090"
        assert compute_cap == (8, 9)

    @patch("airpods.system._run_command")
    @patch("airpods.system.shutil.which")
    def test_parse_error_handling(self, mock_which, mock_run_command):
        """Test handling of malformed nvidia-smi output."""
        mock_which.return_value = "/usr/bin/nvidia-smi"
        mock_run_command.return_value = (True, "NVIDIA RTX 4090, malformed_capability")

        has_gpu, gpu_name, compute_cap = detect_cuda_compute_capability()

        assert has_gpu is False
        assert "NVIDIA RTX 4090" in gpu_name
        assert "compute capability parse failed" in gpu_name
        assert compute_cap is None

    @patch("airpods.system._run_command")
    @patch("airpods.system.shutil.which")
    def test_missing_comma_in_output(self, mock_which, mock_run_command):
        """Test handling when output format is unexpected (no comma)."""
        mock_which.return_value = "/usr/bin/nvidia-smi"
        mock_run_command.return_value = (True, "NVIDIA RTX 4090")  # No comma separator

        has_gpu, gpu_name, compute_cap = detect_cuda_compute_capability()

        assert has_gpu is False
        assert "NVIDIA RTX 4090" in gpu_name
        assert "compute capability parse failed" in gpu_name
        assert compute_cap is None


class TestCudaCompatibilityMap:
    """Tests for the CUDA compatibility mapping data structure."""

    def test_map_contains_expected_architectures(self):
        """Test that map contains entries for major GPU architectures."""
        # Kepler/Maxwell era
        assert (3, 5) in CUDA_COMPATIBILITY_MAP
        assert (5, 2) in CUDA_COMPATIBILITY_MAP

        # Pascal/Turing era
        assert (6, 1) in CUDA_COMPATIBILITY_MAP
        assert (7, 5) in CUDA_COMPATIBILITY_MAP

        # Ampere era
        assert (8, 6) in CUDA_COMPATIBILITY_MAP

        # Hopper era
        assert (9, 0) in CUDA_COMPATIBILITY_MAP

    def test_map_values_are_valid_cuda_versions(self):
        """Test that all values in the map are valid CUDA version strings."""
        valid_versions = {"cu118", "cu126", "cu128", "cu130"}

        for compute_cap, cuda_version in CUDA_COMPATIBILITY_MAP.items():
            assert cuda_version in valid_versions, (
                f"Invalid CUDA version: {cuda_version} for {compute_cap}"
            )

    def test_newer_architectures_get_newer_cuda(self):
        """Test that newer GPU architectures generally get newer CUDA versions."""
        # This is a general trend, not a strict requirement

        # Older architectures should get older CUDA
        assert CUDA_COMPATIBILITY_MAP[(3, 5)] in ["cu118"]
        assert CUDA_COMPATIBILITY_MAP[(7, 5)] in ["cu126"]

        # Newer architectures should get newer CUDA
        assert CUDA_COMPATIBILITY_MAP[(8, 6)] in ["cu128", "cu130"]
        assert CUDA_COMPATIBILITY_MAP[(9, 0)] in ["cu128", "cu130"]


class TestComfyuiImageMap:
    """Tests for the ComfyUI image mapping data structure."""

    def test_all_cuda_versions_have_images(self):
        """Test that all CUDA versions from compatibility map have corresponding images."""
        cuda_versions_in_use = set(CUDA_COMPATIBILITY_MAP.values())
        cuda_versions_in_use.add("cpu")  # CPU should always be available

        for cuda_version in cuda_versions_in_use:
            assert cuda_version in COMFYUI_IMAGES, (
                f"No image defined for CUDA version: {cuda_version}"
            )

    def test_images_have_correct_format(self):
        """Test that all image names follow expected Docker format."""
        for cuda_version, image in COMFYUI_IMAGES.items():
            # Should be docker registry format
            assert "/" in image, f"Image {image} doesn't look like a valid Docker image"
            assert image.startswith("docker.io/yanwk/comfyui-boot:"), (
                f"Unexpected image format: {image}"
            )

    def test_default_cuda_version_exists_in_images(self):
        """Test that the default CUDA version has a corresponding image."""
        assert DEFAULT_CUDA_VERSION in COMFYUI_IMAGES
