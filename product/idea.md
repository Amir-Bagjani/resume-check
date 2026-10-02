# Idea

# Resume Screening Application

I want to build a web-based application for reviewing and filtering resumes in bulk.

The first version should have a simple Web UI. The user provides the path to a local folder containing a large number of resumes. The resumes may be in PDF or Microsoft Word formats.

The main purpose of the application is to automatically review all resumes in that folder, extract relevant information from them, compare that information against criteria provided by the user, and separate the resumes that match those criteria.

## Main User Flow

The user should first specify the folder that contains the resumes.

After selecting the folder, the user should be able to define one or more screening criteria.

The screening criteria should be optional individually. The application should not require every field to be filled. However, at least one screening criterion must be provided before the screening process can start, because the purpose of the application is to filter resumes according to user-defined requirements.

For the first version, we mainly need the following criteria.

### Years of Work Experience

The user should be able to specify a minimum required number of years of professional experience.

For example:

- Minimum experience: 5 years

The application should analyze each resume and determine the candidate's approximate total professional experience.

It should then determine whether the candidate satisfies the minimum experience requirement.

The application should also handle cases where work experience cannot be determined.

For example, a candidate may:

- have 7 years of experience;
- have 3 years of experience;
- not mention enough information to reliably calculate work experience.

The system should preserve this information in the final report instead of simply marking everything as passed or failed.

### Required Technologies / Keywords

The user should also be able to specify technologies, skills, or keywords that must appear in the resume.

For example, if we are reviewing resumes for a Frontend Developer position, the user may specify:

- React
- Material UI
- TypeScript

If React is a required technology, resumes that only mention Vue.js or Angular but do not demonstrate React experience should not qualify based on that criterion.

The UI should allow the user to add multiple required technologies or keywords.

This should be designed in a flexible way because additional screening criteria may be added to the application later.

## Resume Analysis

After the user defines the criteria and starts the screening process, the application should process every supported resume inside the selected folder.

For each resume, it should try to extract information such as:

- Candidate name, when available
- Total or estimated years of work experience
- Technologies and skills mentioned in the resume
- Whether each user-defined criterion was satisfied
- Any information that could not be determined reliably

The application should then determine whether the resume qualifies according to the criteria selected by the user.

The result should not only contain a final qualified/not-qualified status. It should also explain why that decision was made.

For example:

- Candidate has 6 years of work experience and mentions React and Material UI.
- Candidate has only 3 years of work experience.
- Candidate meets the experience requirement but React was not found in the resume.
- Work experience could not be determined from the resume.
- Candidate mentions React but does not mention Material UI.

## Output Folder

After processing is completed, the application should automatically create a new output folder inside the original folder selected by the user.

The folder name should clearly indicate that it contains the screening results and should include the current Persian/Jalali date.

For example:

`resume-screening-output-1405-07-10`

The exact naming convention can be refined later, but the Persian/Jalali date must be included.

## Qualified Resumes

The resumes that satisfy all active screening criteria should be copied into the generated output folder.

The original resume files must remain unchanged.

Only qualified resumes should be copied into the result folder.

## Excel Report

The application should also generate an Excel report inside the output folder.

The report should summarize the complete screening process.

At the top level, it should provide information such as:

- Total number of resumes found
- Total number of resumes successfully processed
- Number of qualified resumes
- Number of non-qualified resumes
- Number of resumes that could not be fully analyzed, if applicable
- Screening criteria used for this run
- Date of the screening

The report should also contain one row for every resume that was processed.

For example, useful columns may include:

- Resume file name
- Candidate name
- Estimated years of experience
- Experience status
- Technologies / skills detected
- Required technologies found
- Required technologies missing
- Final status
- Reason / explanation

Example results could look conceptually like this:

| Candidate | Experience | Required Skills | Result | Reason |
|---|---:|---|---|---|
| Candidate A | 7 years | React, Material UI | Qualified | Meets experience and technology requirements |
| Candidate B | 3 years | React | Not Qualified | Does not meet the 5-year experience requirement |
| Candidate C | Unknown | React, Material UI | Not Qualified / Undetermined | Work experience could not be determined |
| Candidate D | 6 years | Vue, Angular | Not Qualified | React was required but was not found |

The Excel report is important because the user should be able to understand exactly what happened to every resume, not only see the selected files.

## Processing Summary in the UI

After processing is completed, the Web UI should also show a simple summary.

For example:

- 50 resumes found
- 50 resumes processed
- 18 qualified
- 29 not qualified
- 3 could not be fully analyzed

The user should also be able to see where the output folder was created.

## Important Product Requirements

The screening process should be explainable. The system should not silently reject a resume without showing the reason.

The application should distinguish between:

- a candidate clearly failing a criterion;
- information simply not being available in the resume.

The original resume files must never be modified or deleted.

Only matching resumes should be copied to the generated output directory.

All resumes should still appear in the Excel report regardless of whether they qualified.

The initial version only needs to support a Web UI and local folder-based processing.

The product should be designed so that new screening criteria can be added later without redesigning the entire workflow.

Possible future criteria might include things such as:

- education level;
- university;
- location;
- language proficiency;
- specific job titles;
- specific companies or industries;
- minimum experience with a particular technology;
- required or excluded keywords.

These are not required for the first version, but the product design should not make adding them difficult.

## First-Version Scope

For the initial version, focus on this workflow:

User selects a folder containing PDF and Word resumes → user defines optional screening criteria such as minimum years of experience and required technology keywords → application analyzes every resume → application explains the result for every candidate → qualified resumes are copied into a dated output folder → a complete Excel report is generated inside the same folder → the Web UI shows a processing summary.

At this stage, the goal is to define and build a practical first version of the product. Avoid introducing unrelated features or unnecessary complexity.
