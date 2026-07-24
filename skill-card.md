## Description: <br>
Converts coordinates among WGS-84, GCJ-02, and BD-09, and supports control-point affine/polynomial fitting, Helmert transforms, and batch conversion of CSV, GeoJSON, or Shapefile data. <br>

This skill is ready for commercial/non-commercial use. <br>

## Publisher: <br>
[ruiduobao](https://clawhub.ai/user/ruiduobao) <br>

### License/Terms of Use: <br>
MIT-0 <br>


## Use Case: <br>
Developers and GIS engineers use this skill to convert coordinates between common China mapping systems, fit local transforms from their own control points, and batch-convert user-selected map data files. It is appropriate for visualization, product, and data-preparation workflows, not for legal, surveying, emergency, or other high-accuracy location decisions when using the approximate GCJ-02 method. <br>

### Deployment Geography for Use: <br>
Global; intended for workflows involving mainland China coordinate systems. <br>

## Known Risks and Mitigations: <br>
Risk: The approximate GCJ-02 method can produce systematic location error and is not suitable for legal, surveying, emergency, or other high-accuracy decisions. <br>
Mitigation: Use the control-point affine/polynomial or Helmert workflows with your own high-quality control points, validate residuals, and keep approximate conversions limited to non-surveying uses. <br>
Risk: Batch and vector commands create or overwrite destination files selected by the user. <br>
Mitigation: Review input and output paths before execution and write to a new or backed-up destination when preserving existing data matters. <br>
Risk: Transform quality depends on the quality and distribution of control points. <br>
Mitigation: Use locally collected, well-distributed control points and inspect residual statistics before relying on converted coordinates. <br>
Risk: Shapefile conversion does not automatically copy sidecar files such as .prj or .cpg. <br>
Mitigation: Copy required sidecar files with the converted Shapefile and verify CRS and encoding metadata in downstream GIS tools. <br>


## Reference(s): <br>
- [ClawHub skill page](https://clawhub.ai/ruiduobao/skills/china-coord-transform) <br>
- [Project homepage](https://github.com/ruiduobao/china-coord-transform) <br>
- [Artifact README](artifact/README.md) <br>
- [Artifact license](artifact/LICENSE) <br>


## Skill Output: <br>
**Output Type(s):** [text, markdown, code, shell commands, configuration, files] <br>
**Output Format:** [Markdown guidance with Python and CLI snippets; commands may produce coordinate text, CSV, GeoJSON, Shapefile, or JSON parameter files.] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [Runs locally with Python over user-selected input and output paths; Shapefile support requires optional pyshp.] <br>

## Skill Version(s): <br>
1.1.1 (source: server release metadata and SKILL.md frontmatter) <br>

## Ethical Considerations: <br>
Users should evaluate whether this skill is appropriate for their environment, review any generated or modified files before relying on them, and apply their organization's safety, security, and compliance requirements before deployment. <br>
