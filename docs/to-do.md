## Tasks to do

### 5. Update the data models

The current prescription workflow takes the audiogram and goes straight to compressor LUTs and bias gains. This workflow doesn't consider our separation described in `prescription-data-model.md`. Update the workflow to consider this data model. This means that:
- The workstation should be able to store audiograms;
- The workstation should be able to store "calibration profiles";
- The workstation should use the **audiogram** and the **prescriptive formula** to generate the prescription;
- The workstation should use the **prescription** and the **calibration profile** to generate the DSP parameters (LUTs and bias gains);
