1. group

    - group1: note1, note4
    - group2: note2,note3
    - In setting window:

      ```
      group1 :
      ├ note1
      └ note4
      group2:
      ├ note2
      └ note3
      ```

    - For each note settig, add group default, which uses group setting.
      - e.g., font color:  ("group" button)  ("select..." button)
    - data structure: it is an attribute of the note window.

      ```json
      {
      "note_name":
        {
          text_font_family: "cica"
          group: "some group"
        }
      }

      ```

1. general setting

    - data structure: top level like,

    ```json
    {
      "app_setting":{
        "font" : "cica",
        "backup": "disable",
      },
      "note_name": {
      },
      "note_name2":{
      },
    }
    ```
