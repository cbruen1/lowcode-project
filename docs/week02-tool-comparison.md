# Week 2 — AI Tool Comparison
 
## The requirement
Add a contact form to your Flask application. It must:
- render at /contact with fields for name, email and message
- validate that the email address is well-formed server side
- reject empty name or message fields with a visible error
- on success, show a confirmation page
- store nothing yet — persistence comes in Week 5
 
## Prompts used
### Claude
**Prompt 1 command**: "Make a contact form."  
**Prompt 1 result**: Claude created a html form with javascript for validation, no server side code. This partially worked: it prevented most invalid email addresses using javascript but allowed addresses in "a@b.c" format. Also enforced all required fields. Allowed "\<script\>alert(1)\</script\>" in Message field.

**Prompt 2 command**: "Write a contact form for a Flask application. Use Flask 3.x and Jinja2 templates. Give me templates/contact.html and the route."  
**Prompt 2 result**: This created an app.py file with server-side validation and a templates/contact.html file. Enforced all required fields and valid email address but still allowed addresses in "a@b.c" format. Still allowed "\<script\>alert(1)\</script\>" in Message field.

**Prompt 3 command**: "Write a contact form for a Flask application. Use Flask 3.x and Jinja2 templates. Give me templates/contact.html and the route. Validate name, email and message on the server. Do not use any package outside Flask and the standard library. Return the form with an error message if validation fails."  
**Prompt 3 result**: Very little change after this, just a slight update to app.py with new summary message, everything else the same.

**Prompt 4 command**: "That validation accepts \<script\>alert(1)\</script\> as valid input in the Message field. Tighten it, and tell me what it will now reject that it previously accepted."  
**Prompt 4 result**: This resulted in updated validation, "a@b.c" no longer accepted as email address. Stated "One caveat first. \<script\>alert(1)\</script\> was never executable in this app, because Jinja2 autoescapes it when the form is shown again". 


### Gemini
**Prompt 1 command**: "Make a contact form."  
**Prompt 1 result**: Created html only with attributes for validation, no javascript. Only partially worked, mandatory fields were enforced but some invalid emails were allowed e.g. "a@b.". Allowed "<script>alert(1)</script>" in Message field. Gemini couldn't write to local file system so code output had to be copied and pasted and files created manually.

**Prompt 2 command**: "Write a contact form for a Flask application. Use Flask 3.x and Jinja2 templates. Give me templates/contact.html and the route."  
**Prompt 2 result**: Created server-side validation but threw multiple syntax errors on submit. 

**Prompt 3 command**: "Write a contact form for a Flask application. Use Flask 3.x and Jinja2 templates. Give me templates/contact.html and the route. Validate name, email and message on the server. Do not use any package outside Flask and the standard library. Return the form with an error message if validation fails."  
**Prompt 3 result**: Slight improvement, all mandatory fields were enforced, email validation still not working correctly, no runtime errors. 

**Prompt 4 command**: "That validation accepts \<script\>alert(1)\</script\> as valid input in the Message field. Tighten it, and tell me what it will now reject that it previously accepted."  
**Prompt 4 result**: Added validation to prevent HTML tags and script elements in Message fields. Email validation still not fully correct. HTML tags still allowed in Name field.

 
## Scores

| Criterion | Claude | Gemini | 
|-------------|-------------|-------------|
| **Correctness** | Score: 5. Worked after the final prompt, all validation correct on final attempt. | Score: 3. Only partially working after the final prompt, some validation failing. No upper bound on name, email, or message size. |
| **Code quality** | Score: 4. Good quality code, understandable variable names, separate function for validation. Used a CSRF token to prevent forged cross site requests. However no unit tests. | Score: 3. Reasonable quality code, understandable variable names, separate function for validation. No CSRF token, no unit tests. |
| **Completeness** | Score: 4. Code is complete for the given requirements, handled the edge and error cases as well as happy path.  | Score: 3. Code isn't fully complete for the given requirements, handled the edge and error cases as well as happy path but some validation issues remain. |
| **Security** | Score: 3. Secret Key: Default secret key used. If deployed without setting SECRET_KEY, session cookies become predictable. Should raise runtime error if deployed without setting secret key.  Debug mode enabled: If accidentally deployed, Flask's debugger can expose sensitive information. No rate limiter or request size limits, these should be added to prevent denial of service and email flooding. | Score: 3. Secret Key: Default secret key used. If deployed without setting SECRET_KEY, session cookies become predictable. Should raise runtime error if deployed without setting secret key.  Debug mode enabled: If accidentally deployed, Flask's debugger can expose sensitive information. No rate limiter or request size limits, these should be added to prevent denial of service and email flooding. No bot protection. |


 
## What each got wrong

**Claude**  
This is a good junior-to-mid-level Flask contact form implementation. It demonstrates awareness of common web security issues (CSRF, validation, bot prevention, input sanitisation) and the overall structure is clean and maintainable. However, it is not production-ready yet as the fallback secret key is insecure, debug mode is enabled, and there is no rate limiting or hardened session configuration. With those issues fixed, I would consider it a solid foundation for a small production contact form.

**Gemini**  
The code is a good educational or portfolio-level Flask form and demonstrates a reasonable understanding of request handling, validation, flashing messages, and the Post/Redirect/Get pattern.
However, from a professional security perspective, the absence of CSRF protection, the hard-coded secret key, enabled debug mode, and absence of anti-spam controls mean it is not yet suitable for deployment on a public website without further work.
 
## Which I kept, and why
I would keep the Claude version. It feels like code written by someone thinking about production security and real-world web development, whereas the second feels more like an educational example that demonstrates form validation but leaves several important concerns unaddressed. The Claude version has CSRF protection, better anti-spam measures, more complete validation, and better handling of secrets. It's not perfect (debug mode, logging PII, no rate limiting), but it has much stronger foundations and would require significantly less work to make production-ready. 